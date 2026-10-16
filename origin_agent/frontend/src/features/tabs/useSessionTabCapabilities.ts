import { useCallback, useEffect, useRef, useState } from "react";
import { TIMING } from "../../constants/timing";
import { subscribeChatAgentspaceEvents } from "../../services/chatAgentspaceEventBus";
import { useChatRuntimeStore } from "../chat/chatRuntimeStore";
import { variableEventRelevant } from "../sessionVariables/presentation";
import { fetchSessionTabCapabilities } from "./sessionTabCapabilitiesApi";
import type { SessionTabCapabilitiesDto } from "./sessionTabCapabilitiesApi";

export type SessionTabCapabilitiesStatus = "idle" | "loading" | "refreshing" | "ready" | "error";

export interface UseSessionTabCapabilitiesState {
  status: SessionTabCapabilitiesStatus;
  capabilities: SessionTabCapabilitiesDto | null;
}

export function useSessionTabCapabilities(sessionId: string): UseSessionTabCapabilitiesState {
  const [status, setStatus] = useState<SessionTabCapabilitiesStatus>("idle");
  const [capabilities, setCapabilities] = useState<SessionTabCapabilitiesDto | null>(null);
  const generation = useRef(0);
  const request = useRef<AbortController | null>(null);
  const refreshTimer = useRef<number | null>(null);
  const current = useRef({ sessionId, status, capabilities });
  current.current = { sessionId, status, capabilities };

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    const owner = ++generation.current;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    const previous = current.current;
    const hasSnapshot = previous.sessionId === sessionId
      && previous.capabilities !== null
      && previous.capabilities.session_id === sessionId;
    if (hasSnapshot) {
      setStatus("refreshing");
    } else {
      setCapabilities(null);
      setStatus("loading");
    }
    try {
      const result = await fetchSessionTabCapabilities(sessionId, controller.signal);
      if (generation.current !== owner || current.current.sessionId !== sessionId || controller.signal.aborted) return;
      setCapabilities(result);
      setStatus("ready");
    } catch (failure) {
      if (controller.signal.aborted || generation.current !== owner
        || current.current.sessionId !== sessionId) return;
      void failure;
      setCapabilities(null);
      setStatus("error");
    } finally {
      if (generation.current === owner && request.current === controller) {
        request.current = null;
      }
    }
  }, [sessionId]);
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;

  useEffect(() => {
    generation.current += 1;
    request.current?.abort();
    request.current = null;
    setCapabilities(null);
    setStatus("idle");
    if (sessionId) void refreshRef.current();
    return () => {
      generation.current += 1;
      request.current?.abort();
      request.current = null;
    };
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    const scheduleRefresh = () => {
      if (refreshTimer.current !== null) window.clearTimeout(refreshTimer.current);
      refreshTimer.current = window.setTimeout(() => {
        refreshTimer.current = null;
        void refreshRef.current();
      }, TIMING.SESSION_TAB_CAPABILITIES_REFRESH_DEBOUNCE);
    };
    const unsubscribeHistory = useChatRuntimeStore.subscribe((state, previous) => {
      if (state.sessionId !== sessionId) return;
      if (state.knownHistoryCount === previous.knownHistoryCount
        && state.skeleton === previous.skeleton
        && state.currentStreamId === previous.currentStreamId
        && state.processing === previous.processing) return;
      scheduleRefresh();
    });
    const unsubscribeAgentspace = subscribeChatAgentspaceEvents((event) => {
      if (variableEventRelevant(event, sessionId)) scheduleRefresh();
    });
    return () => {
      unsubscribeHistory();
      unsubscribeAgentspace();
      if (refreshTimer.current !== null) window.clearTimeout(refreshTimer.current);
      refreshTimer.current = null;
    };
  }, [sessionId]);

  return { status, capabilities };
}
