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
  it("toggles historical messages and keeps their UI choice after page reload", () => {
    const store = useChatRuntimeStore.getState();
    const message = { role: "tool" as const, content: "result", id: "history:1:tool:0" };
    store.mergeHistoryPage([message], 1, 2);
    store.toggleMessageCollapse(message.id, "history");
    expect(useChatRuntimeStore.getState().contentByRowId[message.id].collapsed).toBe(false);
    store.mergeHistoryPage([{ ...message, content: "updated" }], 1, 2);
    expect(useChatRuntimeStore.getState().contentByRowId[message.id]).toMatchObject({
      content: "updated", collapsed: false,
    });
    store.toggleMessageCollapse(message.id, "history");
    expect(useChatRuntimeStore.getState().contentByRowId[message.id].collapsed).toBe(true);
  });

  it("preserves live folding during stream updates and completion", () => {
    const store = useChatRuntimeStore.getState();
    store.appendLiveMessage({ role: "tool", content: "call", id: "live-tool" }, true);
    const cutoff = useChatRuntimeStore.getState().liveVersion;
    const rowVersion = useChatRuntimeStore.getState().liveRows[0].version;
    store.toggleMessageCollapse("live-tool", "live");
    expect(useChatRuntimeStore.getState().liveRows[0].message.collapsed).toBe(false);
    expect(useChatRuntimeStore.getState().liveVersion).toBe(cutoff);
    expect(useChatRuntimeStore.getState().liveRows[0].version).toBe(rowVersion);
    store.applyStreamBatch({ streamId: "live-tool", delta: "!", reasoningDelta: "" });
    expect(useChatRuntimeStore.getState().liveRows[0].message.collapsed).toBe(false);
    store.finishStream("live-tool");
    expect(useChatRuntimeStore.getState().liveRows[0].message.collapsed).toBe(false);
    store.toggleMessageCollapse("live-tool", "live");
    expect(useChatRuntimeStore.getState().liveRows[0].message.collapsed).toBe(true);
  });

  it("does not retain a canonical live row after a UI-only toggle", () => {
    const store = useChatRuntimeStore.getState();
    store.appendLiveMessage({ role: "tool", content: "result", id: "tool" });
    const cutoff = useChatRuntimeStore.getState().liveVersion;
    store.toggleMessageCollapse("tool", "live");
    expect(useChatRuntimeStore.getState().liveVersion).toBe(cutoff);
    store.reconcileCanonicalTail(cutoff);
    expect(useChatRuntimeStore.getState().liveRows).toEqual([]);
  });

  it("ignores missing messages and clears folding on session reset", () => {
    const store = useChatRuntimeStore.getState();
    store.mergeHistoryPage([{ role: "tool", content: "result", id: "history:0:tool:0" }], 0, 1);
    store.appendLiveMessage({ role: "tool", content: "call", id: "live-tool" });
    const before = useChatRuntimeStore.getState();
    store.toggleMessageCollapse("missing", "history");
    store.toggleMessageCollapse("missing", "live");
    expect(useChatRuntimeStore.getState()).toBe(before);
    store.toggleMessageCollapse("history:0:tool:0", "history");
    store.toggleMessageCollapse("live-tool", "live");
    store.beginSession("another-session");
    expect(useChatRuntimeStore.getState().contentByRowId).toEqual({});
    expect(useChatRuntimeStore.getState().liveRows).toEqual([]);
  });
  it("keeps a visible ordinary long stream expanded until a manual collapse", () => {
    const store = useChatRuntimeStore.getState();
    store.appendLiveMessage({ id: "read", role: "assistant", content: "a" }, true);
    store.queueStreamFinish("read", "x".repeat(1300));
    expect(useChatRuntimeStore.getState().liveRows[0].streaming).toBe(true);
    store.finishStream("read", "x".repeat(1300), undefined, true);
    const current = useChatRuntimeStore.getState();
    expect(current.liveRows[0].message.collapsed).toBe(false);
    expect(current.liveRows[0].preserveExpanded).toBe(true);
    store.toggleMessageCollapse("read", "live");
    expect(useChatRuntimeStore.getState().liveRows[0].message.collapsed).toBe(true);
  });

  it("leaves offscreen, short and tool messages at their previous defaults", () => {
    const store = useChatRuntimeStore.getState();
    store.appendLiveMessage({ id: "off", role: "assistant", content: "a" }, true);
    store.appendLiveMessage({ id: "short", role: "assistant", content: "a" }, true);
    store.appendLiveMessage({ id: "tool", role: "tool", content: "a" }, true);
    store.finishStream("off", "x".repeat(1300), undefined, false);
    store.finishStream("short", "short", undefined, true);
    store.finishStream("tool", "x".repeat(1300), undefined, true);
    expect(useChatRuntimeStore.getState().liveRows.every((row) => !row.preserveExpanded)).toBe(true);
    store.appendLiveMessage({ id: "manual", role: "assistant", content: "x".repeat(1300) }, true);
    store.toggleMessageCollapse("manual", "live");
    store.finishStream("manual", undefined, undefined, true);
    expect(useChatRuntimeStore.getState().liveRows.find((row) => row.id === "manual")?.preserveExpanded).toBeFalsy();
  });

  it("hands a visible stream to its authoritative History row before page merge", () => {
    const store = useChatRuntimeStore.getState();
    store.appendLiveMessage({ id: "first", role: "assistant", content: "x".repeat(1300), characterName: "main-agent" }, true);
    store.finishStream("first", undefined, undefined, true);
    const cutoff = useChatRuntimeStore.getState().liveVersion;
    store.linkStreamHistory("first", 4);
    store.mergeHistoryPage([{
      id: "history:4:message", role: "assistant", content: "updated",
      messageIndex: 4, characterName: "main-agent",
    }], 4, 5, cutoff);
    expect(useChatRuntimeStore.getState().contentByRowId["history:4:message"].collapsed).toBe(false);
    expect(useChatRuntimeStore.getState().liveRows).toEqual([]);
    store.mergeHistoryPage([{
      id: "history:4:message", role: "assistant", content: "reloaded", messageIndex: 4,
    }], 4, 5);
    expect(useChatRuntimeStore.getState().contentByRowId["history:4:message"].collapsed).toBe(false);
    store.toggleMessageCollapse("history:4:message", "history");
    expect(useChatRuntimeStore.getState().contentByRowId["history:4:message"].collapsed).toBe(true);
  });

  it("transfers after a page arrives first, and rejects a mismatched character", () => {
    const store = useChatRuntimeStore.getState();
    store.appendLiveMessage({ id: "later", role: "assistant", content: "x".repeat(1300), characterName: "agent-a" }, true);
    store.finishStream("later", undefined, undefined, true);
    store.mergeHistoryPage([{
      id: "history:2:message", role: "assistant", content: "parsed content",
      messageIndex: 2, characterName: "agent-a",
    }], 2, 3);
    store.linkStreamHistory("later", 2);
    expect(useChatRuntimeStore.getState().contentByRowId["history:2:message"].collapsed).toBe(false);
    expect(useChatRuntimeStore.getState().liveRows).toEqual([]);
    store.appendLiveMessage({ id: "wrong", role: "assistant", content: "x".repeat(1300), characterName: "agent-b" }, true);
    store.finishStream("wrong", undefined, undefined, true);
    store.linkStreamHistory("wrong", 2);
    expect(useChatRuntimeStore.getState().streamHistoryLinks.wrong).toBeUndefined();
  });

  it("drops an unlinked live row atomically with the canonical page and resets pending state", () => {
    const store = useChatRuntimeStore.getState();
    store.appendLiveMessage({ id: "orphan", role: "assistant", content: "x".repeat(1300) }, true);
    store.queueStreamFinish("orphan", "x".repeat(1300));
    store.finishStream("orphan", undefined, undefined, true);
    const cutoff = useChatRuntimeStore.getState().liveVersion;
    store.mergeHistoryPage([{
      id: "history:0:message", role: "assistant", content: "x".repeat(1300), messageIndex: 0,
    }], 0, 1, cutoff);
    expect(useChatRuntimeStore.getState().liveRows).toEqual([]);
    expect(useChatRuntimeStore.getState().contentByRowId["history:0:message"].collapsed).toBeUndefined();
    store.beginSession("new");
    expect(useChatRuntimeStore.getState().pendingStreamFinishes).toEqual({});
    expect(useChatRuntimeStore.getState().streamHistoryLinks).toEqual({});
  });
  it("keeps separate links for equal-content streams until a failed page is retried", () => {
    const store = useChatRuntimeStore.getState();
    for (const id of ["one", "two"]) {
      store.appendLiveMessage({ id, role: "assistant", content: "x".repeat(1300) }, true);
      store.finishStream(id, undefined, undefined, true);
    }
    store.linkStreamHistory("one", 2);
    store.linkStreamHistory("two", 3);
    store.setPageError({ key: "2:4", startIndex: 2, endIndex: 4, message: "unavailable", retryable: true });
    store.reconcileCanonicalTail(useChatRuntimeStore.getState().liveVersion);
    expect(useChatRuntimeStore.getState().liveRows).toHaveLength(2);
    store.mergeHistoryPage([
      { id: "history:2:message", role: "assistant", content: "x".repeat(1300), messageIndex: 2 },
      { id: "history:3:message", role: "assistant", content: "x".repeat(1300), messageIndex: 3 },
    ], 2, 4);
    expect(useChatRuntimeStore.getState().liveRows).toEqual([]);
    expect(useChatRuntimeStore.getState().contentByRowId["history:2:message"].collapsed).toBe(false);
    expect(useChatRuntimeStore.getState().contentByRowId["history:3:message"].collapsed).toBe(false);
    expect(useChatRuntimeStore.getState().pageErrors).toEqual({});
  });
});

describe("follow reducer", () => {
  it("does not follow after an explicit user departure", () => {
    expect(reduceFollowMode("following", { type: "USER_LEFT_BOTTOM" })).toBe("detached");
    expect(reduceFollowMode("detached", { type: "RETURN_START" })).toBe("returning");
    expect(reduceFollowMode("returning", { type: "RETURN_DONE" })).toBe("following");
  });
});
