import { useCallback, useEffect, useRef } from "react";
import type { VirtuosoHandle } from "react-virtuoso";
import { HISTORY_NEAR_BOTTOM_ROWS } from "../../constants/history";
import { DIMENSIONS } from "../../constants/dimensions";
import {
  buildHeightWeightedSegments,
  normalizeScrollMetrics,
  scrollTopToLogicalRange,
} from "./minimapGeometry";
import { chatRuntimeController } from "./chatRuntimeController";
import { useChatRuntimeStore } from "./chatRuntimeStore";
import { chatTelemetry } from "./chatTelemetry";
import type { ChatFollowMode, ChatVisibleRange } from "./types";

const NESTED_SCROLL_SELECTOR = ".tool-call-detail, .message-content-collapsed, .reasoning-content, .context-extension-content";

function nestedScrollConsumes(event: WheelEvent): boolean {
  if (!(event.target instanceof Element)) return false;
  const nested = event.target.closest<HTMLElement>(NESTED_SCROLL_SELECTOR);
  if (!nested || nested.scrollHeight <= nested.clientHeight || event.deltaY === 0) return false;
  const atTop = nested.scrollTop <= 0;
  const atBottom = nested.scrollTop + nested.clientHeight >= nested.scrollHeight - 1;
  return event.deltaY < 0 ? !atTop : !atBottom;
}

function nestedTouchConsumes(event: TouchEvent): boolean {
  if (!(event.target instanceof Element)) return false;
  const nested = event.target.closest<HTMLElement>(NESTED_SCROLL_SELECTOR);
  return Boolean(nested && nested.scrollHeight > nested.clientHeight);
}

export type ScrollEvent =
  | { type: "INITIAL_READY" }
  | { type: "USER_LEFT_BOTTOM" }
  | { type: "USER_REACHED_BOTTOM" }
  | { type: "MINIMAP_START" }
  | { type: "MINIMAP_END"; atBottom: boolean }
  | { type: "RETURN_START" }
  | { type: "RETURN_DONE" }
  | { type: "SESSION_RESET" };

export function reduceFollowMode(mode: ChatFollowMode, event: ScrollEvent): ChatFollowMode {
  switch (event.type) {
    case "SESSION_RESET": return "initializing";
    case "INITIAL_READY": return "following";
    case "USER_LEFT_BOTTOM": return "detached";
    case "USER_REACHED_BOTTOM": return "following";
    case "MINIMAP_START": return "minimap_dragging";
    case "MINIMAP_END": return event.atBottom ? "following" : "detached";
    case "RETURN_START": return "returning";
    case "RETURN_DONE": return "following";
    default: return mode;
  }
}

export function useChatScrollController(
  virtuosoRef: React.RefObject<VirtuosoHandle | null>,
  scrollerElement: HTMLElement | null,
) {
  const userIntentUntilRef = useRef(0);
  const followFrameRef = useRef<number | null>(null);
  const metricsFrameRef = useRef<number | null>(null);
  const minimapGenerationRef = useRef<number | null>(null);
  const followMode = useChatRuntimeStore((state) => state.followMode);

  const scheduleScrollMetrics = useCallback(() => {
    if (metricsFrameRef.current !== null) return;
    metricsFrameRef.current = requestAnimationFrame(() => {
      metricsFrameRef.current = null;
      if (!scrollerElement) return;
      useChatRuntimeStore.getState().setScrollMetrics({
        scrollTop: scrollerElement.scrollTop,
        scrollHeight: scrollerElement.scrollHeight,
        viewportHeight: scrollerElement.clientHeight,
      });
    });
  }, [scrollerElement]);

  const transition = useCallback((event: ScrollEvent) => {
    const store = useChatRuntimeStore.getState();
    const next = reduceFollowMode(store.followMode, event);
    if (next !== store.followMode) {
      store.setFollowMode(next);
      chatTelemetry.record({
        time: Date.now(),
        kind: "follow_mode",
        followMode: next,
      });
    }
  }, []);

  const handleRangeChanged = useCallback((range: ChatVisibleRange) => {
    useChatRuntimeStore.getState().setVisibleRange(range);
    chatTelemetry.record({
      time: Date.now(),
      kind: "visible_range",
      startIndex: range.startIndex,
      endIndex: range.endIndex,
    });
    void chatRuntimeController.ensureVisibleRangeLoaded(range.startIndex, range.endIndex);
  }, []);

  const scrollToPhysicalBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    virtuosoRef.current?.scrollTo({ top: Number.MAX_SAFE_INTEGER, behavior });
  }, [virtuosoRef]);

  const scheduleFollowBottom = useCallback(() => {
    if (followFrameRef.current !== null) return;
    followFrameRef.current = requestAnimationFrame(() => {
      followFrameRef.current = null;
      const current = useChatRuntimeStore.getState();
      if (
        current.followMode === "following"
        && !current.userHeightMutation
        && userIntentUntilRef.current <= performance.now()
      ) {
        scrollToPhysicalBottom("auto");
      }
    });
  }, [scrollToPhysicalBottom]);

  const handleAtBottomStateChange = useCallback((atBottom: boolean) => {
    scheduleScrollMetrics();
    const store = useChatRuntimeStore.getState();
    store.setAtBottom(atBottom);
    if (atBottom && store.followMode === "initializing") {
      store.setInitialReady(true);
      transition({ type: "INITIAL_READY" });
      chatTelemetry.record({ time: Date.now(), kind: "initial_bottom" });
      return;
    }
    if (store.userHeightMutation) {
      store.finishUserHeightMutation(atBottom);
      return;
    }
    if (userIntentUntilRef.current > performance.now()) {
      transition({ type: atBottom ? "USER_REACHED_BOTTOM" : "USER_LEFT_BOTTOM" });
      userIntentUntilRef.current = 0;
      return;
    }
    if (!atBottom && store.followMode === "following") {
      scheduleFollowBottom();
    }
    if (atBottom && store.followMode === "returning") {
      transition({ type: "RETURN_DONE" });
    }
  }, [scheduleFollowBottom, scheduleScrollMetrics, transition]);

  const handleTotalListHeightChanged = useCallback(() => {
    scheduleScrollMetrics();
    const store = useChatRuntimeStore.getState();
    if (store.followMode !== "following" || store.userHeightMutation) return;
    scheduleFollowBottom();
  }, [scheduleFollowBottom, scheduleScrollMetrics]);

  const beginUserHeightMutation = useCallback(() => {
    useChatRuntimeStore.getState().beginUserHeightMutation();
  }, []);

  const returnToBottom = useCallback(async () => {
    const state = useChatRuntimeStore.getState();
    if (!state.skeleton.length && !state.liveRows.length) return;
    transition({ type: "RETURN_START" });
    const distance = state.skeleton.length
      ? state.skeleton.length - 1 - state.visibleRange.endIndex
      : 0;
    if (!state.skeleton.length || distance <= HISTORY_NEAR_BOTTOM_ROWS) {
      scrollToPhysicalBottom("smooth");
    } else {
      await chatRuntimeController.jumpToLogicalRow(state.skeleton.length - 1);
      scrollToPhysicalBottom("auto");
    }
    chatTelemetry.record({
      time: Date.now(),
      kind: "return_to_bottom",
      count: distance,
    });
  }, [scrollToPhysicalBottom, transition]);

  const beginMinimapDrag = useCallback(() => {
    const state = useChatRuntimeStore.getState();
    minimapGenerationRef.current = state.generation;
    userIntentUntilRef.current = Number.POSITIVE_INFINITY;
    if (followFrameRef.current !== null) {
      cancelAnimationFrame(followFrameRef.current);
      followFrameRef.current = null;
    }
    transition({ type: "MINIMAP_START" });
  }, [transition]);

  const previewMinimapScrollTop = useCallback((scrollTop: number) => {
    if (!Number.isFinite(scrollTop) || scrollTop < 0) return;
    virtuosoRef.current?.scrollTo({ top: scrollTop, behavior: "auto" });
    scheduleScrollMetrics();
  }, [scheduleScrollMetrics, virtuosoRef]);

  const commitMinimapDrag = useCallback(async (targetScrollTop: number) => {
    const state = useChatRuntimeStore.getState();
    if (minimapGenerationRef.current !== state.generation) return;
    minimapGenerationRef.current = null;
    previewMinimapScrollTop(targetScrollTop);
    const store = useChatRuntimeStore.getState();
    const segments = buildHeightWeightedSegments(
      store.skeleton, store.liveRows, store.rowHeights,
    );
    const metrics = normalizeScrollMetrics({
      ...store.scrollMetrics,
      scrollTop: targetScrollTop,
    });
    const range = scrollTopToLogicalRange(metrics, segments);
    const maxScrollTop = Math.max(0, metrics.scrollHeight - metrics.viewportHeight);
    const atBottom = maxScrollTop - metrics.scrollTop <= DIMENSIONS.SCROLL_BOTTOM_THRESHOLD;
    transition({ type: "MINIMAP_END", atBottom });
    userIntentUntilRef.current = 0;
    if (atBottom) {
      scrollToPhysicalBottom("auto");
    } else {
      await chatRuntimeController.ensureVisibleRangeLoaded(range.startIndex, range.endIndex);
    }
  }, [previewMinimapScrollTop, scrollToPhysicalBottom, transition]);

  useEffect(() => {
    const scroller = scrollerElement;
    if (!scroller) return;
    const markIntent = () => {
      userIntentUntilRef.current = performance.now() + 700;
      if (followFrameRef.current !== null) {
        cancelAnimationFrame(followFrameRef.current);
        followFrameRef.current = null;
      }
    };
    const onPointerDown = (event: PointerEvent) => {
      if (event.target === scroller) markIntent();
    };
    const onWheel = (event: WheelEvent) => {
      if (!nestedScrollConsumes(event)) markIntent();
    };
    const onTouch = (event: TouchEvent) => {
      if (!nestedTouchConsumes(event)) markIntent();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target instanceof Element ? event.target : null;
      if (target?.closest("input, textarea, button, [contenteditable=\"true\"]")) return;
      if (["ArrowDown", "ArrowUp", "End", "Home", "PageDown", "PageUp", " "].includes(event.key)) {
        markIntent();
      }
    };
    const onScroll = () => scheduleScrollMetrics();
    scroller.addEventListener("scroll", onScroll, { passive: true });
    scroller.addEventListener("wheel", onWheel, { passive: true });
    scroller.addEventListener("pointerdown", onPointerDown, { passive: true });
    scroller.addEventListener("touchstart", onTouch, { passive: true });
    scroller.addEventListener("touchmove", onTouch, { passive: true });
    scroller.addEventListener("keydown", onKeyDown);
    const resizeObserver = typeof ResizeObserver === "undefined"
      ? null
      : new ResizeObserver(scheduleScrollMetrics);
    resizeObserver?.observe(scroller);
    scheduleScrollMetrics();
    return () => {
      scroller.removeEventListener("scroll", onScroll);
      scroller.removeEventListener("wheel", onWheel);
      scroller.removeEventListener("pointerdown", onPointerDown);
      scroller.removeEventListener("touchstart", onTouch);
      scroller.removeEventListener("touchmove", onTouch);
      scroller.removeEventListener("keydown", onKeyDown);
      resizeObserver?.disconnect();
      if (metricsFrameRef.current !== null) {
        cancelAnimationFrame(metricsFrameRef.current);
        metricsFrameRef.current = null;
      }
      if (followFrameRef.current !== null) {
        cancelAnimationFrame(followFrameRef.current);
        followFrameRef.current = null;
      }
    };
  }, [scheduleScrollMetrics, scrollerElement]);

  return {
    followMode,
    handleRangeChanged,
    handleAtBottomStateChange,
    handleTotalListHeightChanged,
    beginUserHeightMutation,
    returnToBottom,
    beginMinimapDrag,
    previewMinimapScrollTop,
    commitMinimapDrag,
  };
}
