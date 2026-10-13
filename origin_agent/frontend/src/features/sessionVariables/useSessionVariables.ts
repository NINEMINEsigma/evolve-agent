import { useCallback, useEffect, useRef, useState } from "react";
import { TIMING } from "../../constants/timing";
import { subscribeChatAgentspaceEvents } from "../../services/chatAgentspaceEventBus";
import { fetchSessionVariables, SessionVariablesRequestError } from "./api";
import { variableEventRelevant } from "./presentation";
import type { SessionVariablePoolResponseDto } from "./types";

export interface UseSessionVariablesState {
  pool: SessionVariablePoolResponseDto | null;
  loading: boolean;
  error: string | null;
  syncWarning: string | null;
  refresh: () => Promise<void>;
}

export function useSessionVariables(sessionId: string, active: boolean): UseSessionVariablesState {
  const [pool, setPool] = useState<SessionVariablePoolResponseDto | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [syncWarning, setSyncWarning] = useState<string | null>(null);
  const generation = useRef(0);
  const request = useRef<AbortController | null>(null);
  const current = useRef({ sessionId, active });
  current.current = { sessionId, active };

  const refresh = useCallback(async () => {
    if (!sessionId || !active) return;
    const token = ++generation.current;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    try {
      const result = await fetchSessionVariables(sessionId, controller.signal);
      if (generation.current !== token || current.current.sessionId !== sessionId || !current.current.active) return;
      setPool((previous) => previous?.version === result.version && previous.session_id === sessionId ? previous : result);
      setError(null);
    } catch (failure) {
      // 内部超时控制器触发的 AbortError 已由 api 层转成超时错误；只有
      // 外部 signal 的主动中止才按取消静默丢弃。
      if (failure instanceof DOMException && failure.name === "AbortError" && controller.signal.aborted) return;
      if (generation.current !== token || current.current.sessionId !== sessionId || !current.current.active || controller.signal.aborted) return;
      if (failure instanceof SessionVariablesRequestError && failure.status === 404) setPool(null);
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      if (generation.current === token && current.current.sessionId === sessionId && current.current.active) {
        setLoading(false);
        request.current = null;
      }
    }
  }, [sessionId, active]);

  useEffect(() => {
    ++generation.current;
    request.current?.abort();
    request.current = null;
    setPool(null);
    setError(null);
    setSyncWarning(null);
    setLoading(false);
  }, [sessionId]);

  useEffect(() => {
    if (active && sessionId) void refresh();
    return () => {
      ++generation.current;
      request.current?.abort();
      request.current = null;
      setLoading(false);
    };
  }, [active, sessionId, refresh]);

  useEffect(() => {
    if (!active || !sessionId) return;
    let timer: number | null = null;
    const unsubscribe = subscribeChatAgentspaceEvents((event) => {
      if (event.kind === "watcher_error") {
        setSyncWarning("文件同步已降级，请使用手动刷新确认最新值。");
        return;
      }
      if (event.kind === "resync") setSyncWarning(null);
      if (!variableEventRelevant(event, sessionId)) return;
      if (timer !== null) window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        timer = null;
        void refresh();
      }, TIMING.SESSION_VARIABLES_REFRESH_DEBOUNCE);
    });
    return () => {
      unsubscribe();
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [active, sessionId, refresh]);

  return {
    pool: pool?.session_id === sessionId ? pool : null,
    loading, error, syncWarning, refresh,
  };
}
