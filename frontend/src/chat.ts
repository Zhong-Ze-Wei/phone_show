import type { Phone, Preferences } from "./types";

export const CHAT_STORAGE_KEY = "pick-a-phone.chat.v1";
export const PERSONAS = [
  { id: "tech", label: "科技达人" },
  { id: "lifestyle", label: "生活顾问" },
  { id: "value", label: "性价比专家" },
  { id: "business", label: "商务精英" },
  { id: "gaming", label: "游戏玩家" },
] as const;
export type Persona = (typeof PERSONAS)[number]["id"];
export type MessageStatus =
  | "streaming"
  | "complete"
  | "cancelled"
  | "error"
  | "truncated";
export interface ChatPhone {
  id: string;
  name: string;
  brand: string;
  price: number | null;
  source_url: string | null;
  budget_warning?: string | null;
  chat_warnings?: string[];
}
export interface ChatContext {
  phones: ChatPhone[];
  sources: string[];
  mode:
    | "selected"
    | "recommended"
    | "catalogue"
    | "needs_budget"
    | "no_candidates";
  persona: Persona;
}
export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: MessageStatus;
  context?: ChatContext;
  notice?: string;
}
export interface ChatRequest {
  message: string;
  history: { role: "user" | "assistant"; content: string }[];
  selected_ids: string[];
  preferences: Preferences | null;
  persona: Persona;
}
export type ChatEvent =
  | {
      type: "context";
      data: {
        phones: Phone[];
        sources: string[];
        mode: ChatContext["mode"];
        persona: Persona;
      };
    }
  | { type: "delta"; data: { content: string } }
  | { type: "done"; data: { finish_reason?: string } };

// Only complete question/answer pairs can become model history.
export function completedHistory(
  messages: ChatMessage[],
): ChatRequest["history"] {
  const pairs: ChatRequest["history"][] = [];
  for (let index = 0; index < messages.length - 1; index++) {
    const question = messages[index];
    const answer = messages[index + 1];
    if (
      question.role === "user" &&
      question.status === "complete" &&
      answer.role === "assistant" &&
      answer.status === "complete" &&
      answer.content
    ) {
      pairs.push([
        { role: "user", content: question.content.slice(0, 4000) },
        { role: "assistant", content: answer.content.slice(0, 4000) },
      ]);
      index++;
    }
  }
  return pairs.slice(-6).flat();
}

export function summarizeContext(
  data: Extract<ChatEvent, { type: "context" }>["data"],
): ChatContext {
  return {
    ...data,
    phones: data.phones.map(
      ({
        id,
        name,
        brand,
        price,
        source_url,
        budget_warning,
        chat_warnings,
      }) => ({
        id,
        name,
        brand,
        price,
        source_url,
        budget_warning,
        chat_warnings,
      }),
    ),
    sources: data.sources,
  };
}

export async function consumeChatStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: ChatEvent) => void,
  signal: AbortSignal,
): Promise<{ done: boolean; finish_reason?: string }> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let done = false;
  let finishReason: string | undefined;
  const abort = () => {
    void reader.cancel();
  };
  signal.addEventListener("abort", abort, { once: true });
  function dispatch(block: string) {
    let type = "message";
    const lines: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) type = line.slice(6).trim();
      if (line.startsWith("data:")) lines.push(line.slice(5).trimStart());
    }
    if (!lines.length) return;
    const data = JSON.parse(lines.join("\n"));
    if (type === "error")
      throw new Error(data.message || "顾问响应未完成，请重试。");
    if (type === "context" || type === "delta" || type === "done") {
      if (type === "done") {
        done = true;
        finishReason = data.finish_reason;
      }
      onEvent({ type, data } as ChatEvent);
    }
  }
  try {
    while (!done) {
      if (signal.aborted) throw new DOMException("Aborted", "AbortError");
      const chunk = await reader.read();
      if (signal.aborted) throw new DOMException("Aborted", "AbortError");
      buffer += decoder.decode(chunk.value, { stream: !chunk.done });
      buffer = buffer.replace(/\r\n/g, "\n");
      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        dispatch(block);
        if (done) break;
      }
      if (chunk.done) {
        if (buffer.trim() && !done) dispatch(buffer);
        break;
      }
    }
    return { done, finish_reason: finishReason };
  } finally {
    signal.removeEventListener("abort", abort);
    await reader.cancel();
    reader.releaseLock();
  }
}

export async function streamChat(
  request: ChatRequest,
  signal: AbortSignal,
  onEvent: (event: ChatEvent) => void,
) {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(request),
    signal,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(
      typeof data?.detail === "string"
        ? data.detail
        : `顾问请求未完成（${response.status}）。`,
    );
  }
  if (!response.body) throw new Error("浏览器未能读取顾问响应。");
  return consumeChatStream(response.body, onEvent, signal);
}

export interface ChatSession {
  version: 1;
  persona: Persona;
  messages: ChatMessage[];
}
export function parseChatSession(raw: string): ChatSession {
  if (raw.length > 1_000_000) throw new Error("保存的会话过大，无法加载。");
  const value = JSON.parse(raw);
  const validPersona = (id: unknown): id is Persona =>
    PERSONAS.some((persona) => persona.id === id);
  const modes = [
    "selected",
    "recommended",
    "catalogue",
    "needs_budget",
    "no_candidates",
  ];
  const statuses = ["streaming", "complete", "cancelled", "error", "truncated"];
  if (
    value?.version !== 1 ||
    !validPersona(value.persona) ||
    !Array.isArray(value.messages) ||
    value.messages.length > 40
  )
    throw new Error("保存的会话格式不兼容。");
  const messages: ChatMessage[] = value.messages.map((message: ChatMessage) => {
    if (
      !message ||
      typeof message.id !== "string" ||
      message.id.length > 80 ||
      !["user", "assistant"].includes(message.role) ||
      typeof message.content !== "string" ||
      message.content.length > (message.role === "user" ? 1600 : 16000) ||
      !statuses.includes(message.status) ||
      (message.notice != null &&
        (typeof message.notice !== "string" || message.notice.length > 1000))
    )
      throw new Error("保存的消息格式不兼容。");
    let context: ChatContext | undefined;
    if (message.context) {
      const candidate = message.context;
      if (
        !validPersona(candidate.persona) ||
        !modes.includes(candidate.mode) ||
        !Array.isArray(candidate.phones) ||
        !Array.isArray(candidate.sources) ||
        candidate.sources.some(
          (source) => typeof source !== "string" || source.length > 2000,
        )
      )
        throw new Error("保存的资料来源格式不兼容。");
      const phones = candidate.phones.map((phone) => {
        if (
          !phone ||
          typeof phone.id !== "string" ||
          phone.id.length > 100 ||
          typeof phone.name !== "string" ||
          phone.name.length > 300 ||
          typeof phone.brand !== "string" ||
          phone.brand.length > 100 ||
          !(
            phone.price === null ||
            (typeof phone.price === "number" && Number.isFinite(phone.price))
          ) ||
          !(
            phone.source_url == null ||
            (typeof phone.source_url === "string" &&
              phone.source_url.length <= 2000)
          )
        )
          throw new Error("保存的机型资料格式不兼容。");
        if (
          (phone.budget_warning != null &&
            (typeof phone.budget_warning !== "string" ||
              phone.budget_warning.length > 1000)) ||
          (phone.chat_warnings != null &&
            (!Array.isArray(phone.chat_warnings) ||
              phone.chat_warnings.length > 20 ||
              phone.chat_warnings.some(
                (warning) =>
                  typeof warning !== "string" || warning.length > 1000,
              )))
        )
          throw new Error("保存的机型说明格式不兼容。");
        return {
          id: phone.id,
          name: phone.name,
          brand: phone.brand,
          price: phone.price,
          source_url: phone.source_url || null,
          budget_warning: phone.budget_warning,
          chat_warnings: phone.chat_warnings,
        };
      });
      context = {
        persona: candidate.persona,
        mode: candidate.mode,
        sources: candidate.sources,
        phones,
      };
    }
    return {
      id: message.id,
      role: message.role,
      content: message.content,
      status: message.status === "streaming" ? "cancelled" : message.status,
      notice: message.notice,
      context,
    };
  });
  return { version: 1, persona: value.persona, messages };
}
