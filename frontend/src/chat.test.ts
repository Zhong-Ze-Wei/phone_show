import { afterEach, describe, expect, it, vi } from "vitest";
import {
  completedHistory,
  consumeChatStream,
  parseChatSession,
  streamChat,
  summarizeContext,
  type ChatEvent,
  type ChatMessage,
} from "./chat";
import type { Phone } from "./types";

afterEach(() => vi.unstubAllGlobals());
const encoder = new TextEncoder();
function stream(text: string, chunkSize = 5) {
  const bytes = encoder.encode(text);
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (let offset = 0; offset < bytes.length; offset += chunkSize)
        controller.enqueue(bytes.slice(offset, offset + chunkSize));
      controller.close();
    },
  });
}
const question = (id: string): ChatMessage => ({
  id: `${id}-user`,
  role: "user",
  content: `问题${id}`,
  status: "complete",
});
const answer = (
  id: string,
  status: ChatMessage["status"] = "complete",
): ChatMessage => ({ id, role: "assistant", content: `回答${id}`, status });

describe("真实 SSE 消费", () => {
  it("按 UTF-8 字节拆开的中文和 CRLF 不丢失，按真实事件到达更新", async () => {
    const events: ChatEvent[] = [];
    const text =
      ': keepalive\r\n\r\nevent: delta\r\ndata: {"content":"你好"}\r\n\r\nevent: delta\r\ndata: {"content":"手机"}\r\n\r\nevent: done\r\ndata: {"finish_reason":"stop"}\r\n\r\n';
    const result = await consumeChatStream(
      stream(text, 1),
      (event) => events.push(event),
      new AbortController().signal,
    );
    expect(events).toEqual([
      { type: "delta", data: { content: "你好" } },
      { type: "delta", data: { content: "手机" } },
      { type: "done", data: { finish_reason: "stop" } },
    ]);
    expect(result).toEqual({ done: true, finish_reason: "stop" });
  });
  it("没有 done 的断流保留部分内容，但不会声称完成", async () => {
    const events: ChatEvent[] = [];
    const result = await consumeChatStream(
      stream('event: delta\ndata: {"content":"部分回答"}\n\n'),
      (event) => events.push(event),
      new AbortController().signal,
    );
    expect(events).toHaveLength(1);
    expect(result.done).toBe(false);
  });
  it("错误事件传递真实错误而不标记 done", async () => {
    const events: ChatEvent[] = [];
    await expect(
      consumeChatStream(
        stream(
          'event: delta\ndata: {"content":"部分"}\n\nevent: error\ndata: {"message":"上游中断"}\n\n',
        ),
        (event) => events.push(event),
        new AbortController().signal,
      ),
    ).rejects.toThrow("上游中断");
    expect(events.map((event) => event.type)).toEqual(["delta"]);
  });
  it("停止待返回的流会取消 reader，不再消费旧 delta", async () => {
    const cancel = vi.fn();
    const body = new ReadableStream<Uint8Array>({ cancel });
    const controller = new AbortController();
    const onEvent = vi.fn();
    const promise = consumeChatStream(body, onEvent, controller.signal);
    controller.abort();
    await expect(promise).rejects.toMatchObject({ name: "AbortError" });
    expect(cancel).toHaveBeenCalledOnce();
    expect(onEvent).not.toHaveBeenCalled();
  });
  it("只发送显式当前预算或 null，不从默认预算补值", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(new Response(stream("event: done\ndata: {}\n\n")));
    vi.stubGlobal("fetch", fetch);
    await streamChat(
      {
        message: "我喜欢拍照",
        history: [],
        selected_ids: [],
        preferences: null,
        persona: "lifestyle",
      },
      new AbortController().signal,
      () => {},
    );
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
      message: "我喜欢拍照",
      history: [],
      selected_ids: [],
      preferences: null,
      persona: "lifestyle",
    });
  });
});

describe("会话历史", () => {
  it.each(["streaming", "cancelled", "error", "truncated"] as const)(
    "%s 的部分问答不进入历史，也不留下孤立问题",
    (status) => {
      expect(
        completedHistory([
          question("1"),
          answer("1"),
          question("2"),
          answer("2", status),
          question("3"),
          answer("3"),
        ]),
      ).toEqual([
        { role: "user", content: "问题1" },
        { role: "assistant", content: "回答1" },
        { role: "user", content: "问题3" },
        { role: "assistant", content: "回答3" },
      ]);
    },
  );
  it("历史只保留最近六轮，各条不超过后端 4000 字限制", () => {
    const messages = Array.from({ length: 9 }, (_, index) => [
      question(String(index)),
      { ...answer(String(index)), content: "字".repeat(5000) },
    ]).flat();
    const history = completedHistory(messages);
    expect(history).toHaveLength(12);
    expect(history[0].content).toBe("问题3");
    expect(history[1].content).toHaveLength(4000);
    expect(
      completedHistory([question("1"), { ...answer("1"), content: "" }]),
    ).toEqual([]);
  });
});

describe("手动保存与加载", () => {
  it("保留第 13 条及其后的来源编号，加载中的回答转为未完成", () => {
    const context = summarizeContext({
      phones: [
        {
          id: "1",
          name: "手机",
          brand: "品牌",
          price: 2999,
          source_url: "https://example.com/phone",
          budget_warning: "超预算",
        } as Phone,
      ],
      sources: Array.from(
        { length: 16 },
        (_, index) => `https://example.com/${index + 1}`,
      ),
      mode: "selected",
      persona: "value",
    });
    expect(context.sources[12]).toBe("https://example.com/13");
    const session = parseChatSession(
      JSON.stringify({
        version: 1,
        persona: "value",
        messages: [question("1"), { ...answer("1", "streaming"), context }],
      }),
    );
    expect(session.messages[1].status).toBe("cancelled");
    expect(session.messages[1].context?.sources).toHaveLength(16);
    expect(session.messages[1].context?.phones[0].budget_warning).toBe(
      "超预算",
    );
    expect(completedHistory(session.messages)).toEqual([]);
    expect(session).not.toHaveProperty("preferences");
  });
  it("拒绝格式、消息长度和整体大小异常，不猜测修补会话", () => {
    expect(() => parseChatSession("invalid JSON")).toThrow();
    expect(() =>
      parseChatSession(
        JSON.stringify({ version: 1, persona: "unknown", messages: [] }),
      ),
    ).toThrow("格式");
    expect(() =>
      parseChatSession(
        JSON.stringify({
          version: 1,
          persona: "tech",
          messages: [{ ...question("1"), content: "x".repeat(1601) }],
        }),
      ),
    ).toThrow("格式");
    expect(() => parseChatSession("x".repeat(1_000_001))).toThrow("过大");
    expect(() =>
      parseChatSession(
        JSON.stringify({
          version: 1,
          persona: "tech",
          messages: Array.from({ length: 41 }, (_, index) =>
            question(String(index)),
          ),
        }),
      ),
    ).toThrow("格式");
  });
});
