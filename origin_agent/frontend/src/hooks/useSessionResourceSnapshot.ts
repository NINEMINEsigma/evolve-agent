/**
 * One snapshot per session resource source. Holds a single data value plus one
 * in-flight read; every commit re-checks the Scope (sessionId + generation) and
 * the request Token so an A -> B -> A switch never accepts the first A result.
 * There is no networking here: callers drive beginRequest/completeRequest.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  SessionResourceRequestToken,
  SessionResourceScope,
  SessionResourceSnapshot,
  SessionResourceState,
} from "../types/sessionResources";

interface InFlight {
  token: SessionResourceRequestToken;
  controller: AbortController;
}

const emptySnapshot = <T,>(scope: SessionResourceScope): SessionResourceSnapshot<T> => ({
  sessionId: scope.sessionId,
  generation: scope.generation,
  data: null,
  loading: false,
  error: null,
  updatedAt: null,
});

export function useSessionResourceSnapshot<T>(
  scopeRef: React.MutableRefObject<SessionResourceScope>,
): SessionResourceState<T> {
  const [snapshot, setSnapshot] = useState<SessionResourceSnapshot<T>>(() => emptySnapshot<T>(scopeRef.current));
  const snapshotRef = useRef(snapshot);
  const sequenceRef = useRef(0);
  const inFlightRef = useRef<InFlight | null>(null);
  // 最近一次渲染观察到的 Scope；用于把兼容 setter 绑定到创建时的代际。
  const renderScope = scopeRef.current;

  const commit = useCallback((next: SessionResourceSnapshot<T>) => {
    snapshotRef.current = next;
    setSnapshot(next);
  }, []);

  const scopeMatches = useCallback((scope: SessionResourceScope): boolean => {
    const current = scopeRef.current;
    return current.sessionId === scope.sessionId && current.generation === scope.generation;
  }, [scopeRef]);

  const beginRequest = useCallback((): SessionResourceRequestToken | null => {
    const scope = scopeRef.current;
    if (!scope.sessionId || inFlightRef.current !== null) return null;
    const controller = new AbortController();
    const token: SessionResourceRequestToken = {
      sessionId: scope.sessionId,
      generation: scope.generation,
      sequence: ++sequenceRef.current,
      signal: controller.signal,
    };
    inFlightRef.current = { token, controller };
    const base = snapshotRef.current;
    commit({
      sessionId: scope.sessionId, generation: scope.generation,
      data: base.data, loading: true, error: base.error, updatedAt: base.updatedAt,
    });
    return token;
  }, [commit, scopeRef]);

  const isLiveToken = useCallback((token: SessionResourceRequestToken): boolean => {
    const flight = inFlightRef.current;
    return flight !== null && flight.token === token && !token.signal.aborted && scopeMatches(token);
  }, [scopeMatches]);

  const completeRequest = useCallback((token: SessionResourceRequestToken, data: T): void => {
    if (!isLiveToken(token)) return;
    inFlightRef.current = null;
    commit({
      sessionId: token.sessionId, generation: token.generation,
      data, loading: false, error: null, updatedAt: Date.now(),
    });
  }, [commit, isLiveToken]);

  const failRequest = useCallback((token: SessionResourceRequestToken, error: string): void => {
    if (!isLiveToken(token)) return;
    inFlightRef.current = null;
    commit({
      sessionId: token.sessionId, generation: token.generation,
      data: snapshotRef.current.data, loading: false, error, updatedAt: snapshotRef.current.updatedAt,
    });
  }, [commit, isLiveToken]);

  // 兼容 setter：绑定创建时的渲染 Scope；旧回调在切会话后被实时 Scope 校验丢弃。
  const setData = useMemo<React.Dispatch<React.SetStateAction<T>>>(() => {
    const boundScope: SessionResourceScope = { sessionId: renderScope.sessionId, generation: renderScope.generation };
    return (update: React.SetStateAction<T>): void => {
      if (!scopeMatches(boundScope)) return;
      const current = snapshotRef.current;
      if (current.data === null) return;
      const nextData = typeof update === "function" ? (update as (prev: T) => T)(current.data) : update;
      // 旧操作写入即作废在途 GET，避免迟到响应覆盖已删除/已停止的列表。
      const flight = inFlightRef.current;
      if (flight !== null) {
        flight.controller.abort();
        inFlightRef.current = null;
      }
      commit({ ...current, data: nextData, loading: false });
    };
  }, [renderScope.sessionId, renderScope.generation, commit, scopeMatches]);

  const reset = useCallback((): void => {
    const flight = inFlightRef.current;
    if (flight !== null) {
      flight.controller.abort();
      inFlightRef.current = null;
    }
    commit(emptySnapshot<T>(scopeRef.current));
  }, [commit, scopeRef]);

  useEffect(() => () => {
    const flight = inFlightRef.current;
    if (flight !== null) flight.controller.abort();
    inFlightRef.current = null;
  }, []);

  const exposed = scopeMatches(snapshot) ? snapshot : emptySnapshot<T>(scopeRef.current);
  return { snapshot: exposed, beginRequest, completeRequest, failRequest, setData, reset };
}