import { beforeEach, describe, expect, it, vi } from "vitest";
import { chatRuntimeController } from "./chatRuntimeController";
import { resetChatRuntimeStoreForTest, useChatRuntimeStore } from "./chatRuntimeStore";

function response(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("ChatRuntimeController", () => {
  beforeEach(() => {
    chatRuntimeController.abortAll();
    resetChatRuntimeStoreForTest();
    vi.restoreAllMocks();
  });

  it("initializes skeleton and latest content page", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.includes("/skeleton")) {
        return Promise.resolve(response({
          session_id: "s",
          start_index: 0,
          history_count: 1,
          row_count: 1,
          rows: [{ row_id: "history:0:message", history_index: 0, row_kind: "message", role: "assistant", is_system_status: false }],
        }));
      }
      return Promise.resolve(response({
        session_id: "s",
        start_index: 0,
        end_index: 1,
        history_count: 1,
        rows: [{ row_id: "history:0:message", history_index: 0, row_kind: "message", role: "assistant", is_system_status: false, content: "hello" }],
      }));
    }));
    chatRuntimeController.beginSession("s");
    await chatRuntimeController.initialize("s", 1);
    expect(useChatRuntimeStore.getState().skeleton).toHaveLength(1);
    expect(useChatRuntimeStore.getState().contentByRowId["history:0:message"]?.content).toBe("hello");
  });

  it("drops a stale session response", async () => {
    let resolveFetch!: (value: Response) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => { resolveFetch = resolve; })));
    chatRuntimeController.beginSession("old");
    const initializing = chatRuntimeController.initialize("old", 0);
    chatRuntimeController.beginSession("new");
    resolveFetch(response({ session_id: "old", start_index: 0, history_count: 0, row_count: 0, rows: [] }));
    await initializing;
    expect(useChatRuntimeStore.getState().sessionId).toBe("new");
    expect(useChatRuntimeStore.getState().skeleton).toEqual([]);
  });
});
