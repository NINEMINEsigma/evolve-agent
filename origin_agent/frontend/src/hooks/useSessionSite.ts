/**
 * 会话网页状态 Hook。
 *
 * 探测当前会话的 site/index.html，并通过聊天 WebSocket Agentspace 事件
 * 监听 site/ 目录的文件变化，自动更新右侧入口并刷新已打开的 iframe。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { subscribeChatAgentspaceEvents } from "../services/chatAgentspaceEventBus";
import type { AgentspaceEvent } from "../types";
import { buildSiteUrls } from "../utils";

export type SiteStatus = "idle" | "missing" | "ready";

export interface SessionSiteState {
  status: SiteStatus;
  reloadKey: number;
  urls: ReturnType<typeof buildSiteUrls>;
  refresh: () => void;
}

// 会话网页通常连续部署多个资源；等待安静窗口后再探测并刷新。
const SITE_RELOAD_DEBOUNCE_MS = 1000;

export function useSessionSite(sessionId: string | undefined): SessionSiteState {
  const [status, setStatus] = useState<SiteStatus>("idle");
  const [reloadKey, setReloadKey] = useState(0);

  const urls = useMemo(
    () => buildSiteUrls(sessionId ?? ""),
    [sessionId],
  );
  const probeSeqRef = useRef(0);
  const debounceTimerRef = useRef<number | null>(null);

  const clearPendingRefresh = useCallback(() => {
    if (debounceTimerRef.current != null) {
      window.clearTimeout(debounceTimerRef.current);
      debounceTimerRef.current = null;
    }
  }, []);

  const probe = useCallback(async () => {
    if (!urls) {
      setStatus("missing");
      return;
    }

    const seq = ++probeSeqRef.current;
    try {
      const response = await fetch(urls.indexUrl, { cache: "no-store" });
      if (seq !== probeSeqRef.current) return;
      setStatus(response.ok ? "ready" : "missing");
    } catch {
      if (seq !== probeSeqRef.current) return;
      setStatus("missing");
    }
  }, [urls]);

  const refresh = useCallback(() => {
    clearPendingRefresh();
    setReloadKey((key) => key + 1);
    void probe();
  }, [clearPendingRefresh, probe]);

  // 会话切换时重置状态，并使旧会话尚未完成的探测失效。
  useEffect(() => {
    ++probeSeqRef.current;
    clearPendingRefresh();
    setReloadKey(0);

    if (!sessionId || !urls) {
      setStatus("missing");
      return;
    }

    setStatus("idle");
    void probe();

    return () => {
      ++probeSeqRef.current;
      clearPendingRefresh();
    };
  }, [sessionId, urls, probe, clearPendingRefresh]);

  // 监听当前会话 site/ 的创建、更新、移动和删除事件。
  useEffect(() => {
    if (!sessionId || !urls) return;

    const siteRoot = `sessions/${sessionId}/site`;
    const sitePrefix = `${siteRoot}/`;
    const indexPath = `${sitePrefix}index.html`;

    const isSitePath = (path: string | null): boolean => (
      path === siteRoot || !!path?.startsWith(sitePrefix)
    );

    const markMissing = () => {
      clearPendingRefresh();
      ++probeSeqRef.current;
      setStatus("missing");
    };

    const scheduleRefresh = () => {
      clearPendingRefresh();
      debounceTimerRef.current = window.setTimeout(() => {
        debounceTimerRef.current = null;
        setReloadKey((key) => key + 1);
        void probe();
      }, SITE_RELOAD_DEBOUNCE_MS);
    };

    const handleEvent = (event: AgentspaceEvent) => {
      if (event.kind === "resync") {
        scheduleRefresh();
        return;
      }

      if (
        event.kind === "watcher_error" ||
        event.kind === "locks" ||
        event.kind === "trash_changed"
      ) {
        return;
      }

      if (!isSitePath(event.path) && !isSitePath(event.new_path)) {
        return;
      }

      if (event.kind === "deleted") {
        const deletedIndex = event.path === indexPath;
        const deletedRoot = event.is_directory === true && event.path === siteRoot;
        if (deletedIndex || deletedRoot) {
          markMissing();
          return;
        }
      }

      if (event.kind === "moved") {
        const movedIndexAway = event.path === indexPath && event.new_path !== indexPath;
        const movedRootAway = (
          event.is_directory === true &&
          event.path === siteRoot &&
          event.new_path !== siteRoot
        );
        if (movedIndexAway || movedRootAway) {
          markMissing();
          return;
        }
      }

      scheduleRefresh();
    };

    const cleanup = subscribeChatAgentspaceEvents(handleEvent);

    return () => {
      cleanup();
      clearPendingRefresh();
    };
  }, [sessionId, urls, probe, clearPendingRefresh]);

  return { status, reloadKey, urls, refresh };
}
