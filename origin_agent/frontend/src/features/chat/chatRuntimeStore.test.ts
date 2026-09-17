import { beforeEach, describe, expect, it } from "vitest";
import { reduceFollowMode } from "./useChatScrollController";
import { resetChatRuntimeStoreForTest, useChatRuntimeStore } from "./chatRuntimeStore";

describe("chat runtime store", () => {
  beforeEach(() => resetChatRuntimeStoreForTest());

  it("keeps a stable skeleton reference for stream and page updates", () => {
    const rows = [{
      row_id: "history:0:message",
      history_index: 0,
      row_kind: "message" as const,
      role: "assistant",
      is_system_status: false,
    }];
    useChatRuntimeStore.getState().replaceSkeleton(rows, 1);
    const reference = useChatRuntimeStore.getState().skeleton;
    useChatRuntimeStore.getState().applyStreamBatch({
      streamId: "stream",
      delta: "a",
      reasoningDelta: "",
    });
    useChatRuntimeStore.getState().mergeHistoryPage([
      { role: "assistant", content: "a", id: "history:0:message", messageIndex: 0 },
    ], 0, 1);
    expect(useChatRuntimeStore.getState().skeleton).toBe(reference);
  });

  it("clears Minimap metrics and height measurements for a new session", () => {
    const state = useChatRuntimeStore.getState();
    state.setScrollMetrics({ scrollTop: 340, scrollHeight: 2000, viewportHeight: 500 });
    state.mergeRowHeights([{ id: "history:0:message", height: 460 }]);
    expect(useChatRuntimeStore.getState().rowHeights["history:0:message"]).toBe(460);
    state.beginSession("next-session");
    expect(useChatRuntimeStore.getState().scrollMetrics).toEqual({
      scrollTop: 0, scrollHeight: 0, viewportHeight: 0,
    });
    expect(useChatRuntimeStore.getState().rowHeights).toEqual({});
  });

  it("does not change the virtual list data reference for row measurements", () => {
    const state = useChatRuntimeStore.getState();
    state.replaceSkeleton([{
      row_id: "history:0:message", history_index: 0,
      row_kind: "message", role: "user", is_system_status: false,
    }], 1);
    const skeleton = useChatRuntimeStore.getState().skeleton;
    state.mergeRowHeights([{ id: "history:0:message", height: 91 }]);
    expect(useChatRuntimeStore.getState().skeleton).toBe(skeleton);
  });

  it("clears only live rows covered by canonical cutoff", () => {
    const store = useChatRuntimeStore.getState();
    store.appendLiveMessage({ role: "user", content: "first", id: "first" });
    const cutoff = useChatRuntimeStore.getState().liveVersion;
    store.appendLiveMessage({ role: "user", content: "second", id: "second" });
    store.reconcileCanonicalTail(cutoff);
    expect(useChatRuntimeStore.getState().liveRows.map((row) => row.id)).toEqual(["second"]);
  });
});

describe("follow reducer", () => {
  it("does not follow after an explicit user departure", () => {
    expect(reduceFollowMode("following", { type: "USER_LEFT_BOTTOM" })).toBe("detached");
    expect(reduceFollowMode("detached", { type: "RETURN_START" })).toBe("returning");
    expect(reduceFollowMode("returning", { type: "RETURN_DONE" })).toBe("following");
  });
});
