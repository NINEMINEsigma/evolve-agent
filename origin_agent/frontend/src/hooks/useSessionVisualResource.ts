import { useCallback, useEffect, useRef, useState } from "react";
import { fetchWithTimeout } from "../services/fetchWithTimeout";
import { subscribeChatAgentspaceEvents } from "../services/chatAgentspaceEventBus";
import type { AgentspaceEvent } from "../types";
import type { SessionVisualKind, SessionVisualResourceState } from "../types/sessionVisual";
import { SESSION_VISUAL, SESSION_VISUAL_LAYOUT } from "../constants/sessionVisual";

interface ProbeResult {
  url: string;
  version: string | null;
}

function sourcePrefix(sessionId: string, kind: SessionVisualKind): string {
  return `sessions/${sessionId}/${SESSION_VISUAL_LAYOUT[kind].directory}`;
}

function sourceMetaPath(sessionId: string, kind: SessionVisualKind): string {
  return `${sourcePrefix(sessionId, kind)}${SESSION_VISUAL.META_SUFFIX}`;
}

function matchesPath(path: string | null, root: string): boolean {
  return !!path && (path === root || path.startsWith(`${root}/`));
}

function stripProbeQuery(raw: string): string {
  try {
    const url = new URL(raw, window.location.href);
    for (const name of [SESSION_VISUAL.PROBE_PARAM, SESSION_VISUAL.SID_PARAM, SESSION_VISUAL.KIND_PARAM]) {
      url.searchParams.delete(name);
    }
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return raw;
  }
}

export function useSessionVisualResource(
  sessionId: string | undefined,
  kind: SessionVisualKind,
  paused: boolean = false,
): SessionVisualResourceState {
  const [status, setStatus] = useState<SessionVisualResourceState["status"]>("idle");
  const [finalUrl, setFinalUrl] = useState<string | null>(null);
  const [version, setVersion] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const sequenceRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const debounceRef = useRef<number | null>(null);
  const conflictRef = useRef(0);
  const finalUrlRef = useRef<string | null>(null);
  const versionRef = useRef<string | null>(null);

  const stableUrl = useCallback(() => {
    if (!sessionId) return null;
    const encoded = encodeURIComponent(sessionId);
    const directory = SESSION_VISUAL_LAYOUT[kind].directory;
    const entry = SESSION_VISUAL_LAYOUT[kind].entry;
    const params = new URLSearchParams({
      visual_probe: "1",
      visual_sid: sessionId,
      visual_kind: kind,
    });
    return `/files/ws/sessions/${encoded}/${directory}/${entry}?${params.toString()}`;
  }, [sessionId, kind]);

  const clearTimers = useCallback(() => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
    timerRef.current = null;
    debounceRef.current = null;
  }, []);

  const probe = useCallback(async (preserveReady = false): Promise<ProbeResult | null> => {
    const url = stableUrl();
    if (!url || paused) return null;
    const sequence = ++sequenceRef.current;
    try {
      const response = await fetchWithTimeout(url, { method: "HEAD", cache: "no-store", redirect: "follow" }, {
        timeoutMs: SESSION_VISUAL.TIMEOUT_MS,
        phase: `${kind} 视觉资源探测`,
      });
      if (sequence !== sequenceRef.current) return null;
      if (response.status === 409 && conflictRef.current < SESSION_VISUAL.CONFLICT_RETRIES) {
        conflictRef.current += 1;
        return probe(preserveReady);
      }
      conflictRef.current = 0;
      if (response.status === 503) {
        if (!preserveReady) setStatus("error");
        return null;
      }
      if (!response.ok) {
        if (!preserveReady || response.status === 404) {
          setStatus("missing");
          setFinalUrl(null);
          setVersion(null);
          finalUrlRef.current = null;
          versionRef.current = null;
        }
        return null;
      }
      const result = {
        url: stripProbeQuery(response.url),
        version: response.headers.get(SESSION_VISUAL.VERSION_HEADER),
      };
      const resourceChanged = (
        finalUrlRef.current !== result.url
        || versionRef.current !== result.version
      );
      finalUrlRef.current = result.url;
      versionRef.current = result.version;
      if (preserveReady && resourceChanged) {
        setReloadKey((value) => value + 1);
      }
      setStatus("ready");
      setFinalUrl(result.url);
      setVersion(result.version);
      setError(null);
      return result;
    } catch (caught) {
      if (sequence !== sequenceRef.current) return null;
      if (!preserveReady) {
        setStatus("error");
        setError(caught instanceof Error ? caught.message : "视觉资源探测失败");
      }
      return null;
    }
  }, [kind, paused, stableUrl]);

  const refresh = useCallback(() => {
    clearTimers();
    setReloadKey((value) => value + 1);
    void probe(false);
  }, [clearTimers, probe]);

  useEffect(() => {
    clearTimers();
    ++sequenceRef.current;
    setReloadKey(0);
    setFinalUrl(null);
    setVersion(null);
    finalUrlRef.current = null;
    versionRef.current = null;
    setError(null);
    if (!sessionId || paused) {
      setStatus(paused ? "idle" : "missing");
      return () => clearTimers();
    }
    setStatus("idle");
    void probe();
    return () => {
      ++sequenceRef.current;
      clearTimers();
    };
  }, [sessionId, kind, paused, probe, clearTimers]);

  useEffect(() => {
    if (!sessionId || paused) return;
    const sourceRoot = sourcePrefix(sessionId, kind);
    const metaPath = sourceMetaPath(sessionId, kind);
    let targetRoot: string | null = null;
    const schedule = () => {
      if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
      debounceRef.current = window.setTimeout(() => {
        debounceRef.current = null;
        void probe(true);
      }, SESSION_VISUAL_LAYOUT[kind].debounceMs);
    };
    const handle = (event: AgentspaceEvent) => {
      if (event.kind === "resync") {
        schedule();
        return;
      }
      if (["watcher_error", "locks", "trash_changed"].includes(event.kind)) return;
      if (event.path === metaPath || event.new_path === metaPath || matchesPath(event.path, sourceRoot) || matchesPath(event.new_path, sourceRoot)) {
        schedule();
        return;
      }
      if (targetRoot && (matchesPath(event.path, targetRoot) || matchesPath(event.new_path, targetRoot))) schedule();
    };
    const unsubscribe = subscribeChatAgentspaceEvents(handle);
    const poll = () => {
      if (document.visibilityState === "hidden") {
        timerRef.current = window.setTimeout(poll, SESSION_VISUAL.POLL_MS);
        return;
      }
      void probe(true).then(() => {
        timerRef.current = window.setTimeout(poll, SESSION_VISUAL.POLL_MS);
      });
    };
    timerRef.current = window.setTimeout(poll, SESSION_VISUAL.POLL_MS);
    return () => {
      unsubscribe();
      clearTimers();
      targetRoot = null;
    };
  }, [sessionId, kind, paused, probe, clearTimers]);

  return { status, finalUrl, version, reloadKey, error, refresh };
}
