import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { safeSource } from "./helpers";
import {
  CHAT_STORAGE_KEY,
  PERSONAS,
  completedHistory,
  parseChatSession,
  streamChat,
  summarizeContext,
  type ChatMessage,
  type Persona,
} from "./chat";
import type { Phone, Preferences, Priority } from "./types";

const ANALYSIS_PURPOSES: { id: Priority; label: string }[] = [
  { id: "daily", label: "日常" },
  { id: "camera", label: "拍照" },
  { id: "gaming", label: "游戏" },
  { id: "battery", label: "续航" },
];

export function AnalysisPriorities({
  value,
  onChange,
}: {
  value: Priority[];
  onChange: (value: Priority[]) => void;
}) {
  return (
    <div className="analysis-preferences">
      <span className="analysis-preferences-title">分析偏好</span>
      <div
        className="analysis-purpose-buttons"
        role="group"
        aria-label="AI 分析偏好"
      >
        {ANALYSIS_PURPOSES.map((purpose) => (
          <button
            key={purpose.id}
            aria-pressed={value.includes(purpose.id)}
            className={value.includes(purpose.id) ? "selected" : ""}
            onClick={() =>
              onChange(
                value.includes(purpose.id)
                  ? value.filter((item) => item !== purpose.id)
                  : [...value, purpose.id],
              )
            }
          >
            {purpose.label}
          </button>
        ))}
      </div>
      <p className="analysis-preferences-note">
        只用于顾问分析，不改变左侧筛选。
      </p>
    </div>
  );
}

const QUICK_QUESTIONS = [
  "比较这些手机的优势和取舍",
  "我更重视拍照，怎么选？",
  "哪部更适合长期使用？",
];
const STATUS_LABELS = {
  streaming: "正在响应…",
  complete: "",
  cancelled: "已停止 · 部分回答",
  error: "响应失败 · 部分回答",
  truncated: "回答未完整结束",
};

export default function AdvisorChat({
  open,
  compact,
  onClose,
  preferences,
  invalidPreferences,
  selectedIds,
  candidatePhones,
  catalogueContext,
  contextKey,
  budgetInput,
  onBudget,
  analysisPriorities,
  onAnalysisPriorities,
  preset,
}: {
  open: boolean;
  compact: boolean;
  onClose: () => void;
  preferences: Preferences | null;
  invalidPreferences: boolean;
  selectedIds: string[];
  candidatePhones: Phone[];
  catalogueContext: boolean;
  contextKey: string;
  budgetInput: string;
  onBudget: (value: string) => void;
  analysisPriorities: Priority[];
  onAnalysisPriorities: (value: Priority[]) => void;
  preset: { serial: number; prompt: string } | null;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [persona, setPersona] = useState<Persona>("tech");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const active = useRef<{ id: string; controller: AbortController } | null>(
    null,
  );
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const transcript = useRef<HTMLDivElement>(null);

  function stop(reason = "已停止；部分回答不会用于后续对话。") {
    const request = active.current;
    if (!request) return;
    active.current = null;
    request.controller.abort();
    setMessages((previous) =>
      previous.map((message) =>
        message.id === request.id
          ? { ...message, status: "cancelled", notice: reason }
          : message,
      ),
    );
    setBusy(false);
  }
  useEffect(() => {
    stop(
      open
        ? "条件已更新；旧回答已停止，不会用于后续对话。"
        : "聊天已关闭；部分回答不会用于后续对话。",
    );
    // This effect only cancels; opening, roles and changing conditions never send.
  }, [open, contextKey, persona]);
  useEffect(
    () => () => {
      active.current?.controller.abort();
      active.current = null;
    },
    [],
  );
  useEffect(() => {
    if (!compact) return;
    const element = dialog.current!;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
    return () => {
      if (element.open) element.close();
    };
  }, [open, compact]);
  useEffect(() => {
    if (preset) setDraft(preset.prompt);
  }, [preset]);
  useEffect(() => {
    if (open) input.current?.focus({ preventScroll: true });
  }, [open, preset]);
  useEffect(() => {
    if (open && transcript.current)
      transcript.current.scrollTop = transcript.current.scrollHeight;
  }, [messages, open]);

  async function send() {
    const question = draft.trim();
    if (
      !question ||
      question.length > 1600 ||
      active.current ||
      invalidPreferences
    )
      return;
    const id = crypto.randomUUID();
    const controller = new AbortController();
    active.current = { id, controller };
    const history = completedHistory(messages);
    setMessages((previous) => [
      ...previous.slice(-38),
      { id: `${id}-user`, role: "user", content: question, status: "complete" },
      { id, role: "assistant", content: "", status: "streaming" },
    ]);
    setDraft("");
    setNotice("");
    setBusy(true);
    let content = "";
    let limitReached = false;
    try {
      const result = await streamChat(
        {
          message: question,
          history,
          selected_ids: selectedIds,
          preferences,
          persona,
        },
        controller.signal,
        (event) => {
          if (active.current?.id !== id || controller.signal.aborted) return;
          if (event.type === "context") {
            const context = summarizeContext(event.data);
            setMessages((previous) =>
              previous.map((message) =>
                message.id === id ? { ...message, context } : message,
              ),
            );
          }
          if (event.type === "delta") {
            content += event.data.content;
            if (content.length > 16000) {
              content = content.slice(0, 16000);
              limitReached = true;
              controller.abort();
            }
            setMessages((previous) =>
              previous.map((message) =>
                message.id === id ? { ...message, content } : message,
              ),
            );
          }
        },
      );
      if (active.current?.id !== id) return;
      const complete =
        result.done &&
        (!result.finish_reason || result.finish_reason === "stop") &&
        content.trim().length > 0;
      setMessages((previous) =>
        previous.map((message) =>
          message.id === id
            ? {
                ...message,
                status: complete ? "complete" : "truncated",
                notice: complete
                  ? undefined
                  : "回答未完整结束，不会用于后续对话；可重新发送问题。",
              }
            : message,
        ),
      );
    } catch (error) {
      if (active.current?.id !== id) return;
      setMessages((previous) =>
        previous.map((message) =>
          message.id === id
            ? {
                ...message,
                status: limitReached ? "truncated" : "error",
                notice: limitReached
                  ? "回答超出会话长度限制，已停止，不会用于后续对话。"
                  : error instanceof Error
                    ? error.message
                    : "顾问请求未完成，请重试。",
              }
            : message,
        ),
      );
    } finally {
      if (active.current?.id === id) {
        active.current = null;
        setBusy(false);
      }
    }
  }

  function saveSession() {
    try {
      const raw = JSON.stringify({ version: 1, persona, messages });
      if (raw.length > 1_000_000) {
        setNotice("会话过大，无法保存；可先清空再开始新的对话。");
        return;
      }
      localStorage.setItem(CHAT_STORAGE_KEY, raw);
      setNotice("已手动保存当前会话到本浏览器；不保存预算、筛选或对比机型。");
    } catch {
      setNotice("浏览器无法保存会话；当前对话仍保留在页面中。");
    }
  }
  function loadSession() {
    try {
      const raw = localStorage.getItem(CHAT_STORAGE_KEY);
      if (!raw) {
        setNotice("本浏览器还没有保存的会话。");
        return;
      }
      const session = parseChatSession(raw);
      stop();
      setMessages(session.messages);
      setPersona(session.persona);
      setDraft("");
      setNotice(
        "已加载保存的对话；当前预算、筛选和对比机型保持不变。旧回答的来源仅对应当时条件。",
      );
    } catch (error) {
      setNotice(
        error instanceof Error && error.name !== "SyntaxError"
          ? error.message
          : "保存的会话无法读取，当前对话未更改。",
      );
    }
  }
  function clearSession() {
    stop();
    setMessages([]);
    setDraft("");
    setNotice("当前对话已清空；已保存的会话保留。");
  }
  function handleKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key === "Enter" &&
      (event.ctrlKey || event.metaKey) &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      void send();
    }
  }

  const content = (
    <>
      <header className="chat-header">
        <div>
          <h2 id="advisor-chat-title">AI 选购顾问</h2>
        </div>
        <button
          className="chat-close"
          aria-label="关闭 AI 选购顾问"
          onClick={() => {
            stop();
            onClose();
          }}
        >
          ×
        </button>
      </header>
      <div className="chat-toolbar">
        <label className="chat-persona">
          顾问角色
          <select
            aria-label="顾问角色"
            value={persona}
            onChange={(event) => setPersona(event.target.value as Persona)}
          >
            {PERSONAS.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <div className="chat-session-actions">
          <button onClick={clearSession}>清空</button>
          <button onClick={saveSession}>保存</button>
          <button onClick={loadSession}>加载</button>
        </div>
      </div>
      <details className="chat-options" open={invalidPreferences}>
        <summary>
          偏好与预算
          {analysisPriorities.length > 0
            ? ` · 已选 ${analysisPriorities.length} 项`
            : ""}
        </summary>
        <div className="chat-current-context">
          <label>
            本次预算 <span>¥</span>
            <input
              type="text"
              inputMode="decimal"
              aria-label="聊天最高预算"
              placeholder="留空表示不限"
              aria-invalid={invalidPreferences}
              value={budgetInput}
              onChange={(event) => onBudget(event.target.value)}
            />
          </label>
          <p>
            {invalidPreferences
              ? "请先修正预算；留空表示不限，填写时须大于 0。"
              : selectedIds.length
                ? `优先使用已明确选择的 ${selectedIds.length} 部手机。`
                : preferences
                  ? candidatePhones.length
                    ? catalogueContext
                      ? "发送时读取当前目录，历史与未核价资料会明确说明。"
                      : "发送时从当前筛选的真实候选中比较。"
                    : "当前条件尚无候选；可先调整预算或筛选。"
                  : "预算不限，可直接描述需求并比较机型。"}
          </p>
        </div>
        <AnalysisPriorities
          value={analysisPriorities}
          onChange={onAnalysisPriorities}
        />
      </details>
      {notice && (
        <p className="chat-notice" role="status">
          {notice}
        </p>
      )}
      <div
        className="chat-transcript"
        ref={transcript}
        aria-label="选购顾问对话"
        aria-busy={busy}
      >
        <div className="chat-welcome">
          <strong>你好，我是你的手机选购顾问。</strong>
          <p>
            把左侧的手机拖进来，我们一起比较；也可以直接告诉我你想要什么样的手机。
          </p>
        </div>
        {messages.map((message) => (
          <article
            className={`chat-message chat-${message.role}`}
            key={message.id}
            data-status={message.status}
          >
            <div className="chat-message-label">
              {message.role === "user"
                ? "你"
                : PERSONAS.find((item) => item.id === message.context?.persona)
                    ?.label || "选购顾问"}
              {message.status !== "complete" && (
                <span>{STATUS_LABELS[message.status]}</span>
              )}
            </div>
            {message.content ? (
              <div className="chat-message-content">
                {message.role === "assistant" ? (
                  <ResponseContent message={message} />
                ) : (
                  message.content
                )}
              </div>
            ) : message.status === "streaming" ? (
              <p className="chat-waiting">正在读取资料并等待响应…</p>
            ) : (
              <p className="chat-waiting">本次未收到完整回答。</p>
            )}
            {message.notice && (
              <p
                className="chat-response-notice"
                role={message.status === "error" ? "alert" : undefined}
              >
                {message.notice}
              </p>
            )}
            {message.context && <MessageSources message={message} />}
          </article>
        ))}
      </div>
      <div className="chat-composer">
        <div className="chat-quick-questions" aria-label="快捷问题">
          {QUICK_QUESTIONS.map((question) => (
            <button
              key={question}
              onClick={() => {
                setDraft(question);
                input.current?.focus();
              }}
            >
              {question}
            </button>
          ))}
        </div>
        <div className="chat-input-row">
          <textarea
            ref={input}
            aria-label="发给顾问的问题"
            placeholder="描述用途、在意的体验，或继续追问…"
            value={draft}
            maxLength={1600}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={handleKey}
            rows={3}
          />
          {busy ? (
            <button className="chat-stop-button" onClick={() => stop()}>
              停止
            </button>
          ) : (
            <button
              className="primary-button chat-send-button"
              disabled={!draft.trim() || invalidPreferences}
              onClick={() => void send()}
            >
              发送
            </button>
          )}
        </div>
        <p className="chat-input-hint">
          Ctrl / ⌘ + Enter 发送 · 价格为来源参考价 · 会话最多保留 20 轮
        </p>
      </div>
    </>
  );
  return compact ? (
    <dialog
      ref={dialog}
      className="advisor-chat-dialog"
      aria-labelledby="advisor-chat-title"
      onCancel={(event) => {
        event.preventDefault();
        stop();
        onClose();
      }}
    >
      <section className="advisor-chat">{content}</section>
    </dialog>
  ) : (
    <section
      className="advisor-chat"
      hidden={!open}
      aria-labelledby="advisor-chat-title"
    >
      {content}
    </section>
  );
}

function MessageSources({ message }: { message: ChatMessage }) {
  const context = message.context!;
  return (
    <details className="chat-message-sources">
      <summary>
        {context.phones.length
          ? `${context.mode === "catalogue" ? "本次目录资料" : "本次依据"} · ${context.phones.map((phone) => phone.name).join(" / ")}`
          : context.mode === "needs_budget"
            ? "本条旧对话未指定候选机型"
            : "当前条件无候选机型"}
      </summary>
      {context.phones.map((phone) => (
        <div key={phone.id}>
          <p>
            {phone.brand} {phone.name} ·{" "}
            {phone.price == null
              ? "报价待核实"
              : `参考价 ¥${phone.price.toLocaleString()}`}
            {safeSource(phone.source_url) && (
              <a
                href={safeSource(phone.source_url)!}
                target="_blank"
                rel="noreferrer"
              >
                机型来源 ↗
              </a>
            )}
          </p>
          {[phone.budget_warning, ...(phone.chat_warnings || [])]
            .filter(Boolean)
            .map((warning, index) => (
              <p className="chat-response-notice" key={index}>
                {warning}
              </p>
            ))}
        </div>
      ))}
      {context.sources.map(
        (source, index) =>
          safeSource(source) && (
            <a
              key={`${source}-${index}`}
              href={safeSource(source)!}
              target="_blank"
              rel="noreferrer"
            >
              资料来源 {index + 1} ↗
            </a>
          ),
      )}
      <small>
        这些依据对应本条回答生成时的条件；调整预算后，新问题使用当前条件。
      </small>
    </details>
  );
}

function ResponseContent({ message }: { message: ChatMessage }) {
  return message.content.split(/(\[\d+\])/g).map((part, index) => {
    const reference = /^\[(\d+)\]$/.exec(part);
    const href = reference
      ? safeSource(message.context?.sources[Number(reference[1]) - 1])
      : null;
    return href ? (
      <a
        key={index}
        href={href}
        target="_blank"
        rel="noreferrer"
        aria-label={`资料来源 ${reference![1]}`}
      >
        {part}
      </a>
    ) : (
      part
    );
  });
}
