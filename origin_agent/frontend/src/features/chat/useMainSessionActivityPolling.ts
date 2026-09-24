import { useEffect } from "react";
import { TIMING } from "../../constants/timing";
import { useChatRuntimeStore } from "./chatRuntimeStore";
import { fetchMainSessionStatus } from "./mainSessionActivityApi";

const POLL_WARNING_INTERVAL_MS = 30_000;

export function useMainSessionActivityPolling(
  sessionId: string,
  connected: boolean,
): void {
  useEffect(() => {
    if (!sessionId || !connected) return undefined;

    let disposed = false;
    let timer: number | null = null;
    let controller: AbortController | null = null;
    let inFlight = false;
    let lastWarningAt = 0;

    const stopTimer = () => {
      if (timer !== null) window.clearInterval(timer);
      timer = null;
    };

    const poll = async () => {
      if (disposed || inFlight || document.visibilityState !== "visible") return;
      const runtime = useChatRuntimeStore.getState();
      const generation = runtime.generation;
      if (runtime.sessionId !== sessionId) return;

      inFlight = true;
      controller = new AbortController();
      try {
        const status = await fetchMainSessionStatus(sessionId, controller.signal);
        if (disposed || !status.exists) return;
        const current = useChatRuntimeStore.getState();
        if (current.sessionId !== sessionId || current.generation !== generation) return;
        current.reconcileMainSessionActivity(status);
      } catch (error) {
        if (disposed || controller?.signal.aborted) return;
        const now = Date.now();
        if (now - lastWarningAt >= POLL_WARNING_INTERVAL_MS) {
          lastWarningAt = now;
          console.warn("主会话活动状态查询失败，保留当前气泡状态", error);
        }
      } finally {
        inFlight = false;
        controller = null;
      }
    };

    const startTimer = () => {
      stopTimer();
      if (document.visibilityState !== "visible") return;
      void poll();
      timer = window.setInterval(
        () => { void poll(); },
        TIMING.MAIN_SESSION_ACTIVITY_POLL_INTERVAL,
      );
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        startTimer();
      } else {
        stopTimer();
        controller?.abort();
      }
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    startTimer();

    return () => {
      disposed = true;
      stopTimer();
      controller?.abort();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [connected, sessionId]);
}
