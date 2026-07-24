import { useCallback, useEffect, useRef, useState } from "react";

export type DrawerPhase = "hidden" | "peek" | "open";

export interface EdgeDrawerOptions {
  /** false 时强制归位 hidden 并清理计时器（如断点切换到移动端） */
  active?: boolean;
  /** open/peek 离开抽屉后的自动收回延迟 */
  closeDelay?: number;
  /** 离开热区但未进入抽屉时的收回延迟 */
  peekCloseDelay?: number;
  /** true 时强制保持 open（如抽屉内弹出菜单展开期间）；
   *  解除后若热区与抽屉均未悬停则按 closeDelay 延迟收回，否则保持 */
  pinned?: boolean;
}

export interface EdgeDrawer {
  phase: DrawerPhase;
  hotzoneProps: { onMouseEnter: () => void; onMouseLeave: () => void };
  drawerProps: { onMouseEnter: () => void; onMouseLeave: () => void };
}

/**
 * 边缘自动隐藏抽屉状态机：
 * hidden --热区 enter--> peek --抽屉 enter--> open
 * open   --抽屉 leave--> (热区 enter --> peek) / closeDelay 后 hidden
 * peek   --热区 leave--> peekCloseDelay 后 hidden
 */
export function useEdgeDrawer({
  active = true,
  closeDelay = 400,
  peekCloseDelay = 250,
  pinned = false,
}: EdgeDrawerOptions = {}): EdgeDrawer {
  const [phase, setPhase] = useState<DrawerPhase>("hidden");
  const phaseRef = useRef<DrawerPhase>("hidden");
  const timerRef = useRef<number | null>(null);
  // 热区/抽屉悬停实况：pinned 解除时据此决定保持还是收回
  const hoverRef = useRef({ hotzone: false, drawer: false });
  const pinnedRef = useRef(pinned);
  pinnedRef.current = pinned;

  const setPhaseTracked = useCallback((next: DrawerPhase) => {
    phaseRef.current = next;
    setPhase(next);
  }, []);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const scheduleHide = useCallback(
    (delay: number) => {
      if (pinnedRef.current) return;
      clearTimer();
      timerRef.current = window.setTimeout(() => {
        timerRef.current = null;
        setPhaseTracked("hidden");
      }, delay);
    },
    [clearTimer, setPhaseTracked],
  );

  useEffect(() => {
    if (!active) {
      clearTimer();
      setPhaseTracked("hidden");
    }
  }, [active, clearTimer, setPhaseTracked]);

  // 钉住期间强制 open；解除钉住时按当前悬停实况决定去留
  useEffect(() => {
    if (pinned) {
      clearTimer();
      setPhaseTracked("open");
      return;
    }
    if (
      phaseRef.current !== "hidden" &&
      !hoverRef.current.hotzone &&
      !hoverRef.current.drawer
    ) {
      scheduleHide(closeDelay);
    }
  }, [pinned, closeDelay, clearTimer, setPhaseTracked, scheduleHide]);

  useEffect(() => clearTimer, [clearTimer]);

  const onHotzoneEnter = useCallback(() => {
    hoverRef.current.hotzone = true;
    clearTimer();
    // 钉住期间不得降级为 peek，否则弹出菜单会随抽屉收回而孤立
    setPhaseTracked(pinnedRef.current ? "open" : "peek");
  }, [clearTimer, setPhaseTracked]);

  const onHotzoneLeave = useCallback(() => {
    hoverRef.current.hotzone = false;
    if (phaseRef.current === "peek") scheduleHide(peekCloseDelay);
  }, [peekCloseDelay, scheduleHide]);

  const onDrawerEnter = useCallback(() => {
    hoverRef.current.drawer = true;
    clearTimer();
    setPhaseTracked("open");
  }, [clearTimer, setPhaseTracked]);

  const onDrawerLeave = useCallback(() => {
    hoverRef.current.drawer = false;
    scheduleHide(closeDelay);
  }, [closeDelay, scheduleHide]);

  return {
    phase,
    hotzoneProps: { onMouseEnter: onHotzoneEnter, onMouseLeave: onHotzoneLeave },
    drawerProps: { onMouseEnter: onDrawerEnter, onMouseLeave: onDrawerLeave },
  };
}