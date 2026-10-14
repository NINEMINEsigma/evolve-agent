/**
 * Reusable hover/focus preview state machine with anchored geometry. Owns the
 * open/pending/suppressed lifecycle, modal-block detection, viewport clamping
 * and every timer/observer/listener cleanup. The generic hook imports no tab
 * constants: sizes, gaps and delays are injected through HoverPreviewOptions.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { TAB_PREVIEW } from "../constants/tabPreview";

export interface HoverPreviewOptions<K extends string> {
  scopeKey: string;
  blocked: boolean;
  isEligible: (key: K) => boolean;
  showDelayMs: number;
  hideDelayMs: number;
  width: number;
  maxHeight: number;
  anchorGap: number;
  viewportMargin: number;
}

export type HoverPreviewTriggerProps = Pick<
  React.ButtonHTMLAttributes<HTMLButtonElement>,
  "onPointerEnter" | "onPointerLeave" | "onFocus" | "onBlur"
>;

export type HoverPreviewSurfaceProps = Pick<
  React.HTMLAttributes<HTMLDivElement>,
  "onPointerEnter" | "onPointerLeave"
>;

export interface HoverPreviewState<K extends string> {
  openKey: K | null;
  surfaceRef: React.RefObject<HTMLDivElement>;
  position: { x: number; y: number };
  width: number;
  maxHeight: number;
  surfaceProps: HoverPreviewSurfaceProps;
  getTriggerProps: (key: K) => HoverPreviewTriggerProps;
  dismiss: (suppressUntilExit?: boolean) => void;
  positioned: boolean;
}

type Phase = "idle" | "pending" | "open" | "suppressed";

interface Candidate<K extends string> {
  key: K;
  element: HTMLButtonElement;
}

function finePointer(): boolean {
  return typeof window !== "undefined"
    && window.matchMedia("(hover: hover) and (pointer: fine)").matches;
}

/** body 内存在实际可见的 aria-modal 容器（隐藏 Tab 内的模态不误判）。 */
function hasVisibleModal(): boolean {
  const modals = document.querySelectorAll<HTMLElement>(TAB_PREVIEW.MODAL_SELECTOR);
  for (const modal of modals) {
    if (modal.getClientRects().length === 0) continue;
    const style = window.getComputedStyle(modal);
    if (style.visibility === "hidden" || style.display === "none" || style.opacity === "0") continue;
    return true;
  }
  return false;
}

export function useAnchoredHoverPreview<K extends string>(
  options: HoverPreviewOptions<K>,
): HoverPreviewState<K> {
  const { scopeKey, blocked, isEligible, showDelayMs, hideDelayMs, width, maxHeight, anchorGap, viewportMargin } = options;
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const surfaceRef = useRef<HTMLDivElement>(null);
  const phaseRef = useRef<Phase>("idle");
  const candidateRef = useRef<Candidate<K> | null>(null);
  const pointerInAnchorRef = useRef(false);
  const pointerInSurfaceRef = useRef(false);
  const focusInAnchorRef = useRef(false);
  const lastPointerDownAtRef = useRef(0);
  const showTimerRef = useRef<number | null>(null);
  const hideTimerRef = useRef<number | null>(null);
  const rafRef = useRef<number | null>(null);

  const [openKey, setOpenKey] = useState<K | null>(null);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [effective, setEffective] = useState({ width, maxHeight });
  const [positioned, setPositioned] = useState(false);

  const clearShow = useCallback(() => {
    if (showTimerRef.current !== null) {
      window.clearTimeout(showTimerRef.current);
      showTimerRef.current = null;
    }
  }, []);
  const clearHide = useCallback(() => {
    if (hideTimerRef.current !== null) {
      window.clearTimeout(hideTimerRef.current);
      hideTimerRef.current = null;
    }
  }, []);

  const closeWindow = useCallback(() => {
    clearShow();
    clearHide();
    phaseRef.current = "idle";
    setOpenKey(null);
    setPositioned(false);
  }, [clearShow, clearHide]);

  const dismiss = useCallback((suppressUntilExit = false) => {
    clearShow();
    clearHide();
    if (suppressUntilExit) phaseRef.current = "suppressed";
    setOpenKey(null);
    setPositioned(false);
  }, [clearShow, clearHide]);

  const resetSuppressionIfExited = useCallback(() => {
    // 新的悬停/聚焦是一次全新触发，清除上一次 Escape 留下的抑制。
    if (phaseRef.current === "suppressed") phaseRef.current = "idle";
  }, []);

  /** 打开前的最终条件核对：eligible、blocked、连接、可见性、模态、scope。 */
  const canOpen = useCallback((key: K, element: HTMLButtonElement): boolean => {
    const current = optionsRef.current;
    if (current.blocked) return false;
    if (!current.isEligible(key)) return false;
    if (!element.isConnected) return false;
    if (document.visibilityState !== "visible") return false;
    if (hasVisibleModal()) return false;
    return true;
  }, []);

  const openWindow = useCallback((key: K, element: HTMLButtonElement) => {
    candidateRef.current = { key, element };
    phaseRef.current = "open";
    setPositioned(false);
    setOpenKey(key);
  }, []);

  const scheduleOpen = useCallback((key: K, element: HTMLButtonElement) => {
    clearShow();
    clearHide();
    if (phaseRef.current === "suppressed") return;
    if (!finePointer()) return;
    candidateRef.current = { key, element };
    phaseRef.current = "pending";
    const scopeAtSchedule = optionsRef.current.scopeKey;
    showTimerRef.current = window.setTimeout(() => {
      showTimerRef.current = null;
      const candidate = candidateRef.current;
      if (candidate === null || candidate.key !== key) return;
      if (optionsRef.current.scopeKey !== scopeAtSchedule) return;
      if (!canOpen(key, candidate.element)) {
        phaseRef.current = "idle";
        return;
      }
      openWindow(key, candidate.element);
    }, showDelayMs);
  }, [canOpen, clearHide, clearShow, hideDelayMs, openWindow, showDelayMs]);

  const maybeClose = useCallback(() => {
    if (pointerInAnchorRef.current || pointerInSurfaceRef.current || focusInAnchorRef.current) return;
    if (phaseRef.current === "suppressed") return;
    clearHide();
    hideTimerRef.current = window.setTimeout(() => {
      hideTimerRef.current = null;
      closeWindow();
    }, hideDelayMs);
  }, [clearHide, closeWindow, hideDelayMs]);

  const getTriggerProps = useCallback((key: K): HoverPreviewTriggerProps => ({
    onPointerEnter: (event) => {
      if (event.pointerType !== "mouse") return;
      pointerInAnchorRef.current = true;
      resetSuppressionIfExited();
      scheduleOpen(key, event.currentTarget);
    },
    onPointerLeave: (event) => {
      if (event.pointerType !== "mouse") return;
      pointerInAnchorRef.current = false;
      maybeClose();
    },
    onFocus: (event) => {
      focusInAnchorRef.current = true;
      // 同一锚点在 Escape 抑制后不重开；换到另一锚点则解除抑制。
      if (phaseRef.current === "suppressed" && candidateRef.current?.key === key) return;
      resetSuppressionIfExited();
      // 指针点击引发的焦点不提前开窗；键盘 Tab 聚焦立即开窗。
      if (Date.now() - lastPointerDownAtRef.current < 300) return;
      const element = event.currentTarget;
      if (!canOpen(key, element)) return;
      clearShow();
      clearHide();
      openWindow(key, element);
    },
    onBlur: () => {
      focusInAnchorRef.current = false;
      maybeClose();
    },
  }), [canOpen, clearHide, clearShow, maybeClose, openWindow, resetSuppressionIfExited, scheduleOpen]);

  const surfaceProps: HoverPreviewSurfaceProps = {
    onPointerEnter: () => {
      pointerInSurfaceRef.current = true;
      clearHide();
    },
    onPointerLeave: () => {
      pointerInSurfaceRef.current = false;
      maybeClose();
    },
  };

  // 几何测量：锚点中心对齐真实卡片中心并夹逼到 (visualViewport ∩ layout viewport)。
  // 卡片实际高度由内容决定（≤ maxHeight 上限）：居中与夹逼必须用 surface 的真实
  // rect；若按理论上限高度居中，较矮的卡片会被整体推到锚点上方。
  const measure = useCallback(() => {
    const surface = surfaceRef.current;
    const candidate = candidateRef.current;
    if (surface === null || candidate === null) return;
    const rect = candidate.element.getBoundingClientRect();
    const surfaceRect = surface.getBoundingClientRect();
    const vv = window.visualViewport;
    const vLeft = Math.max(0, vv ? vv.offsetLeft : 0);
    const vTop = Math.max(0, vv ? vv.offsetTop : 0);
    const vRight = Math.min(window.innerWidth, vv ? vv.offsetLeft + vv.width : window.innerWidth);
    const vBottom = Math.min(window.innerHeight, vv ? vv.offsetTop + vv.height : window.innerHeight);
    const availW = Math.max(0, vRight - vLeft - viewportMargin * 2);
    const availH = Math.max(0, vBottom - vTop - viewportMargin * 2);
    const w = Math.min(width, availW);
    const h = Math.min(maxHeight, availH);
    // 首帧 visibility 隐藏仍占据布局，可测得真实宽高；异常零尺寸回退理论值。
    const realW = surfaceRect.width > 0 ? surfaceRect.width : w;
    const realH = surfaceRect.height > 0 ? surfaceRect.height : h;
    const desiredX = rect.left - anchorGap - realW;
    const desiredY = rect.top + rect.height / 2 - realH / 2;
    const maxX = Math.max(vLeft + viewportMargin, vRight - viewportMargin - realW);
    const maxY = Math.max(vTop + viewportMargin, vBottom - viewportMargin - realH);
    const x = Math.min(Math.max(desiredX, vLeft + viewportMargin), maxX);
    const y = Math.min(Math.max(desiredY, vTop + viewportMargin), maxY);
    setEffective((prev) => (prev.width === w && prev.maxHeight === h ? prev : { width: w, maxHeight: h }));
    setPosition((prev) => (prev.x === x && prev.y === y ? prev : { x, y }));
    setPositioned(true);
  }, [anchorGap, maxHeight, viewportMargin, width]);

  const scheduleMeasure = useCallback(() => {
    if (rafRef.current !== null) return;
    rafRef.current = window.requestAnimationFrame(() => {
      rafRef.current = null;
      measure();
    });
  }, [measure]);

  // 打开后首帧测量（避免左上闪帧）；窗口关闭或换锚点时清理。
  useLayoutEffect(() => {
    if (openKey === null) return;
    measure();
  }, [openKey, measure]);

  // ResizeObserver 观察锚点与卡片；窗口 resize / 捕获 scroll / visualViewport 变化同一 rAF。
  useEffect(() => {
    if (openKey === null) return;
    const surface = surfaceRef.current;
    const candidate = candidateRef.current;
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(scheduleMeasure) : null;
    if (observer) {
      if (surface) observer.observe(surface);
      if (candidate) observer.observe(candidate.element);
    }
    window.addEventListener("resize", scheduleMeasure);
    window.addEventListener("scroll", scheduleMeasure, true);
    window.visualViewport?.addEventListener("resize", scheduleMeasure);
    window.visualViewport?.addEventListener("scroll", scheduleMeasure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", scheduleMeasure);
      window.removeEventListener("scroll", scheduleMeasure, true);
      window.visualViewport?.removeEventListener("resize", scheduleMeasure);
      window.visualViewport?.removeEventListener("scroll", scheduleMeasure);
      if (rafRef.current !== null) {
        window.cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [openKey, scheduleMeasure]);

  // 输入来源分类：pointerdown 记录时间；Escape/外部点击/window blur/页面隐藏关闭。
  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      lastPointerDownAtRef.current = Date.now();
      const candidate = candidateRef.current;
      const surface = surfaceRef.current;
      const target = event.target as Node | null;
      if (candidate && target && candidate.element.contains(target)) return;
      if (surface && target && surface.contains(target)) return;
      dismiss(true);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (phaseRef.current !== "open" && phaseRef.current !== "pending") return;
      dismiss(true);
    };
    const onBlur = () => dismiss(true);
    const onVisibility = () => {
      if (document.visibilityState !== "visible") dismiss(true);
    };
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKeyDown);
    window.addEventListener("blur", onBlur);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("blur", onBlur);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [dismiss]);

  // scope 或 blocked 变化 / eligible 失效：关闭并抑制遗留 hover。
  useEffect(() => {
    dismiss(true);
  }, [scopeKey, dismiss]);
  useEffect(() => {
    if (blocked) dismiss(true);
  }, [blocked, dismiss]);
  useEffect(() => {
    const candidate = candidateRef.current;
    if (openKey !== null && (candidate === null || !isEligible(openKey))) dismiss(false);
  }, [openKey, isEligible, dismiss]);

  // 仅存在候选/窗口时启用 MutationObserver；rAF 合并扫描可见模态。
  useEffect(() => {
    if (openKey === null && phaseRef.current !== "pending") return;
    if (typeof MutationObserver === "undefined") return;
    let raf: number | null = null;
    const observer = new MutationObserver(() => {
      if (raf !== null) return;
      raf = window.requestAnimationFrame(() => {
        raf = null;
        if (phaseRef.current === "pending" || phaseRef.current === "open") {
          if (hasVisibleModal()) dismiss(true);
        }
      });
    });
    observer.observe(document.body, {
      childList: true, subtree: true,
      attributes: true, attributeFilter: ["class", "style", "hidden", "aria-modal", "data-active"],
    });
    return () => {
      observer.disconnect();
      if (raf !== null) window.cancelAnimationFrame(raf);
    };
  }, [openKey, dismiss]);

  // 卸载时清理所有定时器与 rAF（StrictMode 对称）。
  useEffect(() => () => {
    if (showTimerRef.current !== null) window.clearTimeout(showTimerRef.current);
    if (hideTimerRef.current !== null) window.clearTimeout(hideTimerRef.current);
    if (rafRef.current !== null) window.cancelAnimationFrame(rafRef.current);
  }, []);

  // 投影核对：锚点卸载或 openKey 与候选不一致时不暴露窗口。
  const candidate = candidateRef.current;
  const projectedOpenKey = openKey !== null && candidate !== null && candidate.key === openKey
    && candidate.element.isConnected && !blocked ? openKey : null;
  const projectedPositioned = projectedOpenKey === null ? false : positioned;

  return {
    openKey: projectedOpenKey,
    surfaceRef,
    position,
    width: effective.width,
    maxHeight: effective.maxHeight,
    surfaceProps,
    getTriggerProps,
    dismiss,
    positioned: projectedPositioned,
  };
}