import { act, renderHook } from "@testing-library/react";
import { createRef } from "react";
import type { VirtuosoHandle } from "react-virtuoso";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetChatRuntimeStoreForTest, useChatRuntimeStore } from "./chatRuntimeStore";
import { useChatScrollController } from "./useChatScrollController";

const frames = new Map<number, FrameRequestCallback>();
let nextId = 0;

function flushFrames(): void {
  const scheduled = [...frames.values()];
  frames.clear();
  act(() => { for (const callback of scheduled) callback(16); });
}

describe("chat scroll metric subscription", () => {
  beforeEach(() => {
    resetChatRuntimeStoreForTest();
    nextId = 0;
    frames.clear();
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      const id = ++nextId;
      frames.set(id, callback);
      return id;
    });
    vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
  });

  afterEach(() => {
    frames.clear();
    vi.unstubAllGlobals();
  });

  it("coalesces scroll events into one physical-metrics update per frame", () => {
    const scroller = document.createElement("div");
    Object.defineProperties(scroller, {
      scrollTop: { value: 300, configurable: true, writable: true },
      scrollHeight: { value: 2000, configurable: true },
      clientHeight: { value: 400, configurable: true },
    });
    const virtuoso = createRef<VirtuosoHandle>();
    const { unmount } = renderHook(() => useChatScrollController(virtuoso, scroller));
    act(() => {
      scroller.dispatchEvent(new Event("scroll"));
      scroller.dispatchEvent(new Event("scroll"));
    });
    expect(frames.size).toBe(1);
    flushFrames();
    expect(useChatRuntimeStore.getState().scrollMetrics).toEqual({
      scrollTop: 300,
      scrollHeight: 2000,
      viewportHeight: 400,
    });
    unmount();
  });
});

describe("chat physical-bottom following", () => {
  beforeEach(() => {
    resetChatRuntimeStoreForTest();
    nextId = 0;
    frames.clear();
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      const id = ++nextId;
      frames.set(id, callback);
      return id;
    });
    vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
  });

  afterEach(() => {
    frames.clear();
    vi.unstubAllGlobals();
  });

  function setupScroll(scrollHeight = 2000, clientHeight = 400) {
    const scroller = document.createElement("div");
    Object.defineProperties(scroller, {
      scrollTop: { value: 300, configurable: true, writable: true },
      scrollHeight: { value: scrollHeight, configurable: true, writable: true },
      clientHeight: { value: clientHeight, configurable: true },
    });
    const scrollTo = vi.fn(({ top }: { top: number }) => { scroller.scrollTop = top; });
    const virtuoso = { current: { scrollTo } as unknown as VirtuosoHandle };
    const hook = renderHook(() => useChatScrollController(virtuoso, scroller));
    return { scroller, scrollTo, virtuoso, ...hook };
  }

  it("follows the full footer bottom synchronously and avoids duplicate writes", () => {
    const { scroller, scrollTo, result, unmount } = setupScroll();
    act(() => useChatRuntimeStore.getState().setFollowMode("following"));
    act(() => result.current.followAfterLiveCommit());
    expect(scrollTo).toHaveBeenCalledWith({ top: 1600, behavior: "auto" });
    expect(scroller.scrollTop).toBe(1600);
    act(() => {
      result.current.handleTotalListHeightChanged();
      result.current.handleAtBottomStateChange(false);
    });
    expect(scrollTo).toHaveBeenCalledTimes(1);
    Object.defineProperty(scroller, "scrollHeight", { value: 2030, configurable: true, writable: true });
    act(() => result.current.handleTotalListHeightChanged());
    expect(scrollTo).toHaveBeenLastCalledWith({ top: 1630, behavior: "auto" });
    scroller.scrollTop = 1629.5;
    act(() => result.current.followAfterLiveCommit());
    expect(scrollTo).toHaveBeenCalledTimes(2);
    unmount();
  });

  it("does not follow a short list, missing handle, or missing scroller", () => {
    const { scroller, scrollTo, virtuoso, result, unmount } = setupScroll(300, 400);
    scroller.scrollTop = 0;
    act(() => useChatRuntimeStore.getState().setFollowMode("following"));
    act(() => result.current.followAfterLiveCommit());
    expect(scrollTo).not.toHaveBeenCalled();
    unmount();

    const absentHandle = setupScroll();
    absentHandle.virtuoso.current = null as unknown as VirtuosoHandle;
    act(() => absentHandle.result.current.followAfterLiveCommit());
    expect(absentHandle.scrollTo).not.toHaveBeenCalled();
    absentHandle.unmount();

    const noScroller = renderHook(() => useChatScrollController(virtuoso, null));
    act(() => noScroller.result.current.followAfterLiveCommit());
    expect(scrollTo).not.toHaveBeenCalled();
    noScroller.unmount();
  });

  it("does not passively follow while detached, dragging, returning, or manually resizing", () => {
    const { scrollTo, result, unmount } = setupScroll();
    for (const mode of ["detached", "minimap_dragging", "returning"] as const) {
      act(() => useChatRuntimeStore.getState().setFollowMode(mode));
      act(() => result.current.followAfterLiveCommit());
    }
    act(() => {
      useChatRuntimeStore.getState().setFollowMode("following");
      useChatRuntimeStore.getState().beginUserHeightMutation();
    });
    act(() => result.current.handleTotalListHeightChanged());
    expect(scrollTo).not.toHaveBeenCalled();
    unmount();
  });

  it("respects user scroll intent before leaving the bottom", () => {
    const { scroller, scrollTo, result, unmount } = setupScroll();
    act(() => useChatRuntimeStore.getState().setFollowMode("following"));
    act(() => scroller.dispatchEvent(new WheelEvent("wheel", { deltaY: -1 })));
    act(() => result.current.followAfterLiveCommit());
    expect(scrollTo).not.toHaveBeenCalled();
    act(() => result.current.handleAtBottomStateChange(false));
    expect(useChatRuntimeStore.getState().followMode).toBe("detached");
    unmount();
  });

  it("aligns the initial footer and keeps explicit return-to-bottom available", async () => {
    const { scrollTo, result, unmount } = setupScroll();
    act(() => result.current.handleAtBottomStateChange(true));
    expect(useChatRuntimeStore.getState().followMode).toBe("following");
    expect(scrollTo).toHaveBeenCalledWith({ top: 1600, behavior: "auto" });
    act(() => useChatRuntimeStore.getState().appendLiveMessage({ id: "live", role: "assistant", content: "new" }));
    await act(async () => { await result.current.returnToBottom(); });
    expect(scrollTo).toHaveBeenLastCalledWith({ top: Number.MAX_SAFE_INTEGER, behavior: "smooth" });
    unmount();
  });

  it("retains explicit minimap positioning at the full footer bottom", async () => {
    const { scrollTo, result, unmount } = setupScroll();
    act(() => useChatRuntimeStore.getState().setScrollMetrics({
      scrollTop: 1500, scrollHeight: 2000, viewportHeight: 400,
    }));
    act(() => result.current.beginMinimapDrag());
    await act(async () => { await result.current.commitMinimapDrag(1600); });
    expect(scrollTo).toHaveBeenLastCalledWith({ top: Number.MAX_SAFE_INTEGER, behavior: "auto" });
    unmount();
  });
});
