import { useCallback, useEffect, useLayoutEffect, useRef } from "react";
import type { VirtuosoHandle } from "react-virtuoso";
import { CHAT_SCROLL_USER_INTENT_MS, HISTORY_NEAR_BOTTOM_ROWS } from "../../constants/history";
import { DIMENSIONS } from "../../constants/dimensions";
import { ROUND_NAV_JUMP_OFFSET_RATIO, ROUND_NAV_NEAR_JUMP_ROWS } from "../../constants/roundNav";
import { normalizeScrollMetrics } from "./scrollGeometry";
import { chatRuntimeController } from "./chatRuntimeController";
import { useChatRuntimeStore, selectChatRenderRows } from "./chatRuntimeStore";
import { chatTelemetry } from "./chatTelemetry";
import type { ChatFollowMode, ChatScrollMetrics, ChatVisibleRange } from "./types";

function readChatScrollMetrics(scroller: HTMLElement | null): ChatScrollMetrics | null {
  if (!scroller) return null;
  const { scrollTop, scrollHeight, clientHeight } = scroller;
  if (![scrollTop, scrollHeight, clientHeight].every(Number.isFinite) || clientHeight <= 0) return null;
  return normalizeScrollMetrics({ scrollTop, scrollHeight, viewportHeight: clientHeight });
}

function isChatAtBottom(metrics: ChatScrollMetrics): boolean {
  return metrics.scrollHeight - metrics.viewportHeight - metrics.scrollTop <= DIMENSIONS.SCROLL_BOTTOM_THRESHOLD;
}

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
  | { type: "RETURN_START" }
  | { type: "RETURN_DONE" }
  | { type: "SESSION_RESET" };

export function reduceFollowMode(mode: ChatFollowMode, event: ScrollEvent): ChatFollowMode {
  switch (event.type) {
    case "SESSION_RESET": return "initializing";
    case "INITIAL_READY": return "following";
    case "USER_LEFT_BOTTOM": return "detached";
    case "USER_REACHED_BOTTOM": return "following";
    case "RETURN_START": return "returning";
    case "RETURN_DONE": return "following";
    default: return mode;
  }
}

export function useChatScrollController(
  virtuosoRef: React.RefObject<VirtuosoHandle | null>,
  scrollerElement: HTMLElement | null,
  topSafeSpacePx: number,
) {
  const userIntentUntilRef = useRef(0);
  const metricsFrameRef = useRef<number | null>(null);
  const metricsFromScrollRef = useRef(false);
  const followFrameRef = useRef<number | null>(null);
  const returnFrameRef = useRef<number | null>(null);
  const returnSequenceRef = useRef(0);
  const returnActionRef = useRef<{ sequence: number; generation: number; ready: boolean } | null>(null);
  const mountedRef = useRef(false);
  const generation = useChatRuntimeStore((state) => state.generation);
  const followMode = useChatRuntimeStore((state) => state.followMode);
  const showSystemUserMessages = useChatRuntimeStore((state) => state.showSystemUserMessages);
  const previousVisibilityRef = useRef(showSystemUserMessages);

  const isCurrent = useCallback(() => (
    mountedRef.current && useChatRuntimeStore.getState().generation === generation
  ), [generation]);

  const transition = useCallback((event: ScrollEvent) => {
    if (!isCurrent()) return;
    const store = useChatRuntimeStore.getState();
    const next = reduceFollowMode(store.followMode, event);
    if (next !== store.followMode) {
      store.setFollowMode(next);
      chatTelemetry.record({ time: Date.now(), kind: "follow_mode", followMode: next });
    }
  }, [isCurrent]);

  const cancelScheduledFollow = useCallback(() => {
    if (followFrameRef.current === null) return;
    cancelAnimationFrame(followFrameRef.current);
    followFrameRef.current = null;
  }, []);

  const cancelReturn = useCallback(() => {
    returnSequenceRef.current += 1;
    returnActionRef.current = null;
    if (returnFrameRef.current !== null) cancelAnimationFrame(returnFrameRef.current);
    returnFrameRef.current = null;
  }, []);

  const interruptAutomaticScroll = useCallback(() => {
    cancelScheduledFollow();
    const wasReturning = useChatRuntimeStore.getState().followMode === "returning";
    cancelReturn();
    // 取消浏览器尚在执行的平滑滚动，不能只取消下一次JS定位。
    if (wasReturning && scrollerElement && isCurrent()) {
      virtuosoRef.current?.scrollTo({ top: scrollerElement.scrollTop, behavior: "auto" });
    }
  }, [cancelReturn, cancelScheduledFollow, isCurrent, scrollerElement, virtuosoRef]);

  const sampleScrollMetrics = useCallback((fromScroll = false): ChatScrollMetrics | null => {
    if (!isCurrent()) return null;
    const metrics = readChatScrollMetrics(scrollerElement);
    if (!metrics) return null;
    const atBottom = isChatAtBottom(metrics);
    const store = useChatRuntimeStore.getState();
    store.setScrollMetrics(metrics);
    if (store.atBottom !== atBottom) store.setAtBottom(atBottom);
    if (store.userHeightMutation) {
      store.finishUserHeightMutation(atBottom);
      return metrics;
    }
    if (atBottom && store.followMode === "initializing") {
      store.setInitialReady(true);
      transition({ type: "INITIAL_READY" });
      chatTelemetry.record({ time: Date.now(), kind: "initial_bottom" });
    } else if (fromScroll && userIntentUntilRef.current > performance.now()) {
      transition({ type: atBottom ? "USER_REACHED_BOTTOM" : "USER_LEFT_BOTTOM" });
    } else if (atBottom && store.followMode === "returning" && returnActionRef.current?.ready) {
      cancelReturn();
      transition({ type: "RETURN_DONE" });
    }
    return metrics;
  }, [cancelReturn, isCurrent, scrollerElement, transition]);

  const scheduleScrollMetrics = useCallback((fromScroll = false) => {
    if (!isCurrent()) return;
    metricsFromScrollRef.current ||= fromScroll;
    if (metricsFrameRef.current !== null) return;
    metricsFrameRef.current = requestAnimationFrame(() => {
      metricsFrameRef.current = null;
      const fromScrollEvent = metricsFromScrollRef.current;
      metricsFromScrollRef.current = false;
      sampleScrollMetrics(fromScrollEvent);
    });
  }, [isCurrent, sampleScrollMetrics]);

  const handleRangeChanged = useCallback((range: ChatVisibleRange) => {
    if (!isCurrent()) return;
    useChatRuntimeStore.getState().setVisibleRange(range);
    chatTelemetry.record({ time: Date.now(), kind: "visible_range", startIndex: range.startIndex, endIndex: range.endIndex });
    void chatRuntimeController.ensureVisibleRangeLoaded(range.startIndex, range.endIndex);
  }, [isCurrent]);

  const scrollToPhysicalBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    if (!isCurrent()) return;
    const metrics = readChatScrollMetrics(scrollerElement);
    if (!metrics) return;
    virtuosoRef.current?.scrollTo({ top: Math.max(0, metrics.scrollHeight - metrics.viewportHeight), behavior });
    scheduleScrollMetrics();
  }, [isCurrent, scheduleScrollMetrics, scrollerElement, virtuosoRef]);

  const followPhysicalBottomNow = useCallback(() => {
    if (!isCurrent()) return;
    const current = useChatRuntimeStore.getState();
    if (current.followMode !== "following" || current.userHeightMutation
      || userIntentUntilRef.current > performance.now() || !virtuosoRef.current) return;
    const metrics = readChatScrollMetrics(scrollerElement);
    if (!metrics) return;
    const target = Math.max(0, metrics.scrollHeight - metrics.viewportHeight);
    if (Math.abs(target - metrics.scrollTop) <= 1) return;
    virtuosoRef.current.scrollTo({ top: target, behavior: "auto" });
  }, [isCurrent, scrollerElement, virtuosoRef]);

  const schedulePhysicalBottomFollow = useCallback(() => {
    if (!isCurrent() || followFrameRef.current !== null) return;
    followFrameRef.current = requestAnimationFrame(() => {
      followFrameRef.current = null;
      followPhysicalBottomNow();
    });
  }, [followPhysicalBottomNow, isCurrent]);

  const scheduleReturnToBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    const action = returnActionRef.current;
    if (!isCurrent() || !action?.ready || action.generation !== generation
      || useChatRuntimeStore.getState().followMode !== "returning" || returnFrameRef.current !== null) return;
    returnFrameRef.current = requestAnimationFrame(() => {
      returnFrameRef.current = null;
      if (!isCurrent() || returnActionRef.current !== action
        || action.sequence !== returnSequenceRef.current
        || useChatRuntimeStore.getState().followMode !== "returning") return;
      if (!readChatScrollMetrics(scrollerElement) || !virtuosoRef.current) {
        cancelReturn();
        transition({ type: "USER_LEFT_BOTTOM" });
        return;
      }
      scrollToPhysicalBottom(behavior);
      sampleScrollMetrics();
    });
  }, [cancelReturn, generation, isCurrent, sampleScrollMetrics, scrollToPhysicalBottom, scrollerElement, transition, virtuosoRef]);

  const followAfterLiveCommit = useCallback(() => {
    scheduleScrollMetrics();
    schedulePhysicalBottomFollow();
    scheduleReturnToBottom();
  }, [schedulePhysicalBottomFollow, scheduleReturnToBottom, scheduleScrollMetrics]);

  const handleAtBottomStateChange = useCallback((_atBottom: boolean) => {
    // Virtuoso布尔回调仅触发采样，DOM物理位置是唯一权威。
    scheduleScrollMetrics();
  }, [scheduleScrollMetrics]);

  const handleTotalListHeightChanged = useCallback(() => {
    scheduleScrollMetrics();
    schedulePhysicalBottomFollow();
    scheduleReturnToBottom();
  }, [schedulePhysicalBottomFollow, scheduleReturnToBottom, scheduleScrollMetrics]);

  const beginUserHeightMutation = useCallback(() => {
    if (!isCurrent()) return;
    interruptAutomaticScroll();
    userIntentUntilRef.current = 0;
    useChatRuntimeStore.getState().beginUserHeightMutation();
    scheduleScrollMetrics();
  }, [interruptAutomaticScroll, isCurrent, scheduleScrollMetrics]);

  const returnToBottom = useCallback(async () => {
    const state = useChatRuntimeStore.getState();
    const rows = selectChatRenderRows(state);
    if (!isCurrent()
      || rows.length === 0
      || !readChatScrollMetrics(scrollerElement) || !virtuosoRef.current) return;
    interruptAutomaticScroll();
    userIntentUntilRef.current = 0;
    if (state.userHeightMutation) state.finishUserHeightMutation(false);
    const action = { sequence: returnSequenceRef.current, generation, ready: false };
    returnActionRef.current = action;
    transition({ type: "RETURN_START" });
    const ownsReturn = () => isCurrent() && returnActionRef.current === action
      && returnSequenceRef.current === action.sequence
      && useChatRuntimeStore.getState().followMode === "returning";
    const failReturn = () => {
      if (!ownsReturn()) return;
      cancelReturn();
      transition({ type: "USER_LEFT_BOTTOM" });
    };
    const distance = rows.length - 1 - state.visibleRange.endIndex;
    const nearBottom = distance <= HISTORY_NEAR_BOTTOM_ROWS;
    try {
      const targetHistoryIndex = rows[rows.length - 1].historyIndex;
      if (!nearBottom && targetHistoryIndex !== null) {
        await chatRuntimeController.jumpToLogicalRow(rows.length - 1);
        if (!ownsReturn()) return;
        const current = useChatRuntimeStore.getState();
        // loadPage将错误写入store而不是重新抛出，不能把Promise完成视为加载成功。
        const targetFailed = Object.values(current.pageErrors).some((error) =>
          error.startIndex <= targetHistoryIndex && error.endIndex > targetHistoryIndex);
        if (targetFailed || !current.loadedHistoryIndices.has(targetHistoryIndex)) {
          failReturn();
          return;
        }
      }
      if (!ownsReturn()) return;
      action.ready = true;
      scheduleReturnToBottom(nearBottom ? "smooth" : "auto");
      chatTelemetry.record({ time: Date.now(), kind: "return_to_bottom", count: distance });
    } catch (error) {
      if (ownsReturn()) {
        console.warn("回到底部未完成", error);
        failReturn();
      }
    }
  }, [cancelReturn, generation, interruptAutomaticScroll, isCurrent, scheduleReturnToBottom, scrollerElement, transition, virtuosoRef]);

  const jumpToRound = useCallback(async (rowIndex: number): Promise<void> => {
    const state = useChatRuntimeStore.getState();
    const rows = selectChatRenderRows(state);
    const row = rows[rowIndex];
    if (!isCurrent() || !row || !virtuosoRef.current) return;
    interruptAutomaticScroll();
    userIntentUntilRef.current = performance.now() + CHAT_SCROLL_USER_INTENT_MS;
    const loaded = row.historyIndex === null
      ? Boolean(row.message)
      : state.loadedHistoryIndices.has(row.historyIndex);
    const far = !loaded || Math.abs(rowIndex - state.visibleRange.startIndex) > ROUND_NAV_NEAR_JUMP_ROWS;
    if (!loaded && row.historyIndex !== null) {
      await chatRuntimeController.jumpToLogicalRow(rowIndex);
      if (!isCurrent()) return;
      // loadPage将错误写入store而不是重新抛出，不能把Promise完成视为加载成功。
      if (!useChatRuntimeStore.getState().loadedHistoryIndices.has(row.historyIndex)) {
        transition({ type: "USER_LEFT_BOTTOM" });
        return;
      }
    }
    if (!isCurrent() || !virtuosoRef.current) return;
    const metrics = readChatScrollMetrics(scrollerElement);
    // 目标消息顶部落在视口中部略偏上的舒适位置。
    // Virtuoso 的条目偏移不包含列表内顶部安全区 spacer，补偿后与 ChatArea 的当前轮参考线严格对齐。
    const offset = metrics
      ? Math.round(topSafeSpacePx - metrics.viewportHeight * ROUND_NAV_JUMP_OFFSET_RATIO)
      : 0;
    virtuosoRef.current.scrollToIndex({ index: rowIndex, align: "start", offset, behavior: far ? "auto" : "smooth" });
    transition({ type: "USER_LEFT_BOTTOM" });
    scheduleScrollMetrics();
  }, [isCurrent, interruptAutomaticScroll, scrollerElement, scheduleScrollMetrics, topSafeSpacePx, transition, virtuosoRef]);

  useLayoutEffect(() => {
    mountedRef.current = true;
    scheduleScrollMetrics();
    return () => {
      mountedRef.current = false;
      cancelScheduledFollow();
      cancelReturn();
      if (metricsFrameRef.current !== null) cancelAnimationFrame(metricsFrameRef.current);
      metricsFrameRef.current = null;
      metricsFromScrollRef.current = false;
      userIntentUntilRef.current = 0;
    };
  }, [cancelReturn, cancelScheduledFollow, generation, scheduleScrollMetrics]);

  useLayoutEffect(() => {
    if (previousVisibilityRef.current === showSystemUserMessages) return;
    previousVisibilityRef.current = showSystemUserMessages;
    // 切换显示属于主动高度操作，取消旧回底动作并按新的展示索引补取内容。
    beginUserHeightMutation();
    const state = useChatRuntimeStore.getState();
    void chatRuntimeController.ensureVisibleRangeLoaded(state.visibleRange.startIndex, state.visibleRange.endIndex);
  }, [beginUserHeightMutation, showSystemUserMessages]);

  useEffect(() => {
    if (followMode !== "following") cancelScheduledFollow();
  }, [cancelScheduledFollow, followMode]);

  useEffect(() => {
    const scroller = scrollerElement;
    if (!scroller) return;
    const markIntent = () => {
      if (!isCurrent()) return;
      interruptAutomaticScroll();
      userIntentUntilRef.current = performance.now() + CHAT_SCROLL_USER_INTENT_MS;
      transition({ type: "USER_LEFT_BOTTOM" });
    };
    const onPointerDown = (event: PointerEvent) => {
      if (event.target === scroller) markIntent();
    };
    const onWheel = (event: WheelEvent) => {
      if (event.deltaY !== 0 && !nestedScrollConsumes(event)) markIntent();
    };
    const onTouch = (event: TouchEvent) => {
      if (!nestedTouchConsumes(event)) markIntent();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target instanceof Element ? event.target : null;
      if (target?.closest("input, textarea, button, [contenteditable=\"true\"]")) return;
      if (["ArrowDown", "ArrowUp", "End", "Home", "PageDown", "PageUp", " "].includes(event.key)) markIntent();
    };
    const onScroll = () => scheduleScrollMetrics(true);
    scroller.addEventListener("scroll", onScroll, { passive: true });
    scroller.addEventListener("wheel", onWheel, { passive: true });
    scroller.addEventListener("pointerdown", onPointerDown, { passive: true });
    scroller.addEventListener("touchstart", onTouch, { passive: true });
    scroller.addEventListener("touchmove", onTouch, { passive: true });
    scroller.addEventListener("keydown", onKeyDown);
    const resizeObserver = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => scheduleScrollMetrics());
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
      if (metricsFrameRef.current !== null) cancelAnimationFrame(metricsFrameRef.current);
      metricsFrameRef.current = null;
      metricsFromScrollRef.current = false;
      cancelScheduledFollow();
    };
  }, [cancelScheduledFollow, interruptAutomaticScroll, isCurrent, scheduleScrollMetrics, scrollerElement, transition]);

  return {
    followMode,
    followAfterLiveCommit,
    handleRangeChanged,
    handleAtBottomStateChange,
    handleTotalListHeightChanged,
    beginUserHeightMutation,
    returnToBottom,
    jumpToRound,
  };
}
