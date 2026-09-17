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
