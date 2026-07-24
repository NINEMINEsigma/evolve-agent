import { useCallback, useEffect, useRef, useState } from "react";

export type DrawerPhase = "hidden" | "peek" | "open";

export interface EdgeDrawerOptions {
  /** false 时强制归位 hidden 并清理计时器（如断点切换到移动端） */
  active?: boolean;
  /** open/peek 离开抽屉后的自动收回延迟 */
  closeDelay?: number;
  /** 离开热区但未进入抽屉时的收回延迟 */
  peekCloseDelay?: number;
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
}: EdgeDrawerOptions = {}): EdgeDrawer {
  const [phase, setPhase] = useState<DrawerPhase>("hidden");
  const phaseRef = useRef<DrawerPhase>("hidden");
  const timerRef = useRef<number | null>(null);

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

  useEffect(() => clearTimer, [clearTimer]);

  const onHotzoneEnter = useCallback(() => {
    clearTimer();
    setPhaseTracked("peek");
  }, [clearTimer, setPhaseTracked]);

  const onHotzoneLeave = useCallback(() => {
    if (phaseRef.current === "peek") scheduleHide(peekCloseDelay);
  }, [peekCloseDelay, scheduleHide]);

  const onDrawerEnter = useCallback(() => {
    clearTimer();
    setPhaseTracked("open");
  }, [clearTimer, setPhaseTracked]);

  const onDrawerLeave = useCallback(() => {
    scheduleHide(closeDelay);
  }, [closeDelay, scheduleHide]);

  return {
    phase,
    hotzoneProps: { onMouseEnter: onHotzoneEnter, onMouseLeave: onHotzoneLeave },
    drawerProps: { onMouseEnter: onDrawerEnter, onMouseLeave: onDrawerLeave },
  };
}