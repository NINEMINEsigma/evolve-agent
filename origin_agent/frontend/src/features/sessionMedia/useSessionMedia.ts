import { useCallback, useEffect, useRef, useState } from "react";
import { SESSION_MEDIA } from "../../constants/sessionMedia";
import { useChatRuntimeStore } from "../chat/chatRuntimeStore";
import { fetchSessionMedia, SessionMediaRequestError, updateSessionMedia } from "./api";
import { mediaInputLabels } from "./labels";
import type {
  SessionMediaAggregateDto, SessionMediaItemDto, SessionMediaListResponseDto, UseSessionMediaState,
} from "./types";

function aggregateOf(page: SessionMediaListResponseDto): SessionMediaAggregateDto {
  return {
    total_count: page.total_count,
    enabled_count: page.enabled_count,
    disabled_count: page.disabled_count,
    enabled_inline_payload_chars: page.enabled_inline_payload_chars,
    disabled_inline_payload_chars: page.disabled_inline_payload_chars,
    enabled_unknown_payload_count: page.enabled_unknown_payload_count,
    disabled_unknown_payload_count: page.disabled_unknown_payload_count,
  };
}

export function useSessionMedia(sessionId: string, active: boolean, archived: boolean): UseSessionMediaState {
  const [page, setPage] = useState<SessionMediaListResponseDto | null>(null);
  const [aggregate, setAggregate] = useState<SessionMediaAggregateDto | null>(null);
  const [offset, changeOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(true);
  const [pendingIds, setPendingIds] = useState<Set<string>>(new Set());
  const [itemErrors, setItemErrors] = useState<Record<string, string>>({});
  const generation = useRef(0);
  const readEpoch = useRef(0);
  const read = useRef<AbortController | null>(null);
  const writes = useRef(new Map<string, AbortController>());
  const refreshWanted = useRef(false);
  const scope = useRef<string | null>(null);
  const current = useRef({ sessionId, active, archived, offset, stale, page, aggregate });
  current.current = { sessionId, active, archived, offset, stale, page, aggregate };

  const refresh = useCallback(async () => {
    if (!sessionId || !active || current.current.sessionId !== sessionId || !current.current.active) return;
    if (writes.current.size > 0) {
      refreshWanted.current = true;
      return;
    }
    refreshWanted.current = false;
    const owner = generation.current;
    const epoch = ++readEpoch.current;
    read.current?.abort();
    const controller = new AbortController();
    read.current = controller;
    setLoading(true);
    try {
      const result = await fetchSessionMedia(sessionId, offset, SESSION_MEDIA.PAGE_SIZE, controller.signal);
      if (generation.current !== owner || readEpoch.current !== epoch
        || current.current.sessionId !== sessionId || !current.current.active
        || current.current.offset !== offset || controller.signal.aborted) return;
      if (result.total_count > 0 && offset >= result.total_count) {
        changeOffset(Math.floor((result.total_count - 1) / SESSION_MEDIA.PAGE_SIZE) * SESSION_MEDIA.PAGE_SIZE);
        return;
      }
      if (result.total_count === 0 && offset !== 0) {
        changeOffset(0);
        return;
      }
      // 先独立提交聚合，再提交当前页；翻页期间旧聚合仍可用。
      setAggregate(aggregateOf(result));
      setPage(result);
      setStale(false);
      setError(null);
      setItemErrors({});
    } catch (failure) {
      if (generation.current !== owner || readEpoch.current !== epoch
        || current.current.sessionId !== sessionId || !current.current.active || controller.signal.aborted) return;
      if (failure instanceof SessionMediaRequestError && failure.status === 404) {
        setPage(null);
        setAggregate(null);
      }
      setStale(true);
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      if (generation.current === owner && readEpoch.current === epoch && current.current.active) {
        setLoading(false);
        read.current = null;
      }
    }
  }, [sessionId, active, offset]);
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;

  const setEnabled = useCallback(async (item: SessionMediaItemDto, enabled: boolean) => {
    const state = current.current;
    if (!state.active || state.archived || state.stale || state.sessionId !== sessionId
      || state.page === null || state.page.session_id !== sessionId || !state.page.editable || writes.current.has(item.media_id)) return;
    const owner = generation.current;
    const controller = new AbortController();
    writes.current.set(item.media_id, controller);
    ++readEpoch.current;
    read.current?.abort();
    read.current = null;
    setLoading(false);
    refreshWanted.current = true;
    setPendingIds(new Set(writes.current.keys()));
    setItemErrors((previous) => {
      const next = { ...previous };
      delete next[item.media_id];
      return next;
    });
    try {
      const result = await updateSessionMedia(
        sessionId, item.media_id, enabled, item.send_multimodal, controller.signal,
      );
      if (generation.current !== owner || current.current.sessionId !== sessionId || !current.current.active) return;
      // 更新只合并自身实例，不能用单项PUT回执覆盖整页或其他并发更新。
      setPage((previous) => previous !== null && previous.session_id === sessionId ? {
        ...previous, items: previous.items.map((entry) => entry.media_id === item.media_id ? result.item : entry),
      } : previous);
    } catch (failure) {
      if (generation.current !== owner || current.current.sessionId !== sessionId || !current.current.active) return;
      const message = failure instanceof Error ? failure.message : String(failure);
      const knownRejection = failure instanceof SessionMediaRequestError
        && [400, 403, 404, 409].includes(failure.status);
      if (failure instanceof SessionMediaRequestError && failure.status === 404) {
        setPage((previous) => previous !== null && previous.session_id === sessionId ? {
          ...previous, items: previous.items.filter((entry) => entry.media_id !== item.media_id),
        } : previous);
      }
      if (!knownRejection) {
        current.current.stale = true;
        setStale(true);
      }
      setItemErrors((previous) => ({
        ...previous,
        [item.media_id]: knownRejection ? message : `${mediaInputLabels.unknownSave} ${message}`,
      }));
    } finally {
      if (writes.current.get(item.media_id) === controller) writes.current.delete(item.media_id);
      if (generation.current === owner && current.current.sessionId === sessionId && current.current.active) {
        setPendingIds(new Set(writes.current.keys()));
        if (writes.current.size === 0 && refreshWanted.current) await refreshRef.current();
      }
    }
  }, [sessionId]);

  // Tab生命周期与页请求分别控制；切页不会撤销同会话已发出的其他实例PUT。
  useEffect(() => {
    ++generation.current;
    ++readEpoch.current;
    read.current?.abort();
    read.current = null;
    for (const controller of writes.current.values()) controller.abort();
    writes.current.clear();
    refreshWanted.current = false;
    setPendingIds(new Set());
    setLoading(false);
    setStale(true);
    if (scope.current !== sessionId) {
      scope.current = sessionId;
      setPage(null);
      setAggregate(null);
      changeOffset(0);
      setError(null);
      setItemErrors({});
    }
    return () => {
      ++generation.current;
      ++readEpoch.current;
      read.current?.abort();
      read.current = null;
      for (const controller of writes.current.values()) controller.abort();
      writes.current.clear();
      refreshWanted.current = false;
    };
  }, [sessionId, active]);

  useEffect(() => {
    if (active && sessionId) void refresh();
    return () => {
      ++readEpoch.current;
      read.current?.abort();
      read.current = null;
    };
  }, [refresh, active, sessionId]);

  useEffect(() => {
    if (!active || !sessionId) return;
    let timer: number | null = null;
    // 仅比较四个低频信号，正文逐帧提交不做派生扫描、不发GET、不触发此hook渲染。
    const unsubscribe = useChatRuntimeStore.subscribe((state, previous) => {
      if (state.sessionId !== sessionId) return;
      if (state.knownHistoryCount === previous.knownHistoryCount && state.skeleton === previous.skeleton
        && state.currentStreamId === previous.currentStreamId && state.processing === previous.processing) return;
      if (timer !== null) window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        timer = null;
        void refreshRef.current();
      }, SESSION_MEDIA.REFRESH_DEBOUNCE_MS);
    });
    return () => {
      unsubscribe();
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [active, sessionId]);

  const setOffset = useCallback((next: number) => {
    if (!Number.isSafeInteger(next) || next < 0) throw new Error("Invalid media page offset");
    changeOffset(next);
  }, []);

  return {
    page: page !== null && page.session_id === sessionId && page.offset === offset ? page : null,
    aggregate: scope.current === sessionId ? aggregate : null,
    offset, loading, error, stale, pendingIds, itemErrors, refresh, setOffset, setEnabled,
  };
}
