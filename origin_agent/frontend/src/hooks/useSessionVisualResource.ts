import { useCallback, useEffect, useRef, useState } from "react";
import { subscribeChatAgentspaceEvents } from "../services/chatAgentspaceEventBus";
import { requestSessionVisualProbe } from "../services/sessionVisualApi";
import type { AgentspaceEvent } from "../types";
import type { SessionVisualKind, SessionVisualProbeResult, SessionVisualResourceState } from "../types/sessionVisual";
import { SESSION_VISUAL, SESSION_VISUAL_LAYOUT } from "../constants/sessionVisual";
import messages from "../constants/sessionVisualMessages.json";

type VisualSnapshot = Omit<SessionVisualResourceState, "refresh">;
type ReadyProbe = Extract<SessionVisualProbeResult, { status: "ready" }>;

function emptySnapshot(idle: boolean): VisualSnapshot {
  return {
    status: idle ? "idle" : "missing", finalUrl: null, version: null,
    reloadKey: 0, error: null, updateStatus: "idle", updateError: null,
  };
}

function matchesPath(path: string | null, root: string): boolean {
  return !!path && (root === "" || path === root || path.startsWith(`${root}/`));
}

function matchesResourcePath(path: string | null, root: string): boolean {
  if (!matchesPath(path, root) || path === null) return false;
  if (path === root) return true;
  const relative = root === "" ? path : path.slice(root.length + 1);
  return !relative.split("/").some(
    (part) => SESSION_VISUAL.SCAN_IGNORED_NAMES.includes(part.toLowerCase()),
  );
}

function targetRoot(finalUrl: string | null): string | null {
  if (!finalUrl) return null;
  const path = new URL(finalUrl, window.location.href).pathname;
  const prefix = `${SESSION_VISUAL.FILES_PREFIX}ws/`;
  if (!path.startsWith(prefix)) return null;
  const relative = path.slice(prefix.length).split("/").map(decodeURIComponent).join("/");
  const separator = relative.lastIndexOf("/");
  return separator === -1 ? "" : relative.slice(0, separator);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : messages.probeError;
}

export function useSessionVisualResource(
  sessionId: string | undefined,
  kind: SessionVisualKind,
  paused: boolean = false,
): SessionVisualResourceState {
  const scope = JSON.stringify([sessionId, kind, paused]);
  const [owned, setOwned] = useState<{ scope: string; value: VisualSnapshot }>(() => ({
    scope, value: emptySnapshot(paused || !!sessionId),
  }));
  const refreshRef = useRef<{ scope: string; run: () => void } | null>(null);
  const refresh = useCallback(() => {
    if (refreshRef.current?.scope === scope) refreshRef.current.run();
  }, [scope]);

  useEffect(() => {
    let snapshot = emptySnapshot(paused || !!sessionId);
    setOwned({ scope, value: snapshot });
    if (!sessionId || paused) return;

    const sid = sessionId;
    const sourceRoot = `sessions/${sid}/${SESSION_VISUAL_LAYOUT[kind].directory}`;
    const metaPath = `${sourceRoot}${SESSION_VISUAL.META_SUFFIX}`;
    let alive = true;
    let generation = 0;
    let controller: AbortController | null = null;
    let inFlight = false;
    let pending = false;
    let timer: number | null = null;
    let debounce: number | null = null;
    let nextChainAt = 0;
    let nextDirectoryAt = 0;
    let directoryVersion: string | null = null;
    let directoryOutcome: "idle" | "ready" | "error" = "idle";

    const publish = (patch: Partial<VisualSnapshot>) => {
      if (!alive) return;
      snapshot = { ...snapshot, ...patch };
      setOwned({ scope, value: snapshot });
    };
    const clearTimer = () => {
      if (timer !== null) window.clearTimeout(timer);
      timer = null;
    };
    const clearDebounce = () => {
      if (debounce !== null) window.clearTimeout(debounce);
      debounce = null;
    };
    const current = (token: number, signal: AbortSignal) => (
      alive && generation === token && !signal.aborted
    );
    const entryFailure = (detail: string) => {
      publish({ status: snapshot.finalUrl ? "ready" : "error", error: detail });
      nextChainAt = performance.now() + SESSION_VISUAL.POLL_MS;
    };
    const directoryFailure = (detail: string) => {
      directoryOutcome = "error";
      publish({ updateStatus: "error", updateError: detail });
      nextDirectoryAt = performance.now() + SESSION_VISUAL.RETRY_MS;
      nextChainAt = performance.now() + SESSION_VISUAL.POLL_MS;
    };

    const canRequest = (manual: boolean) => {
      if (!manual && document.visibilityState === "hidden") {
        pending = true;
        return false;
      }
      return true;
    };
    const readEntry = async (token: number, signal: AbortSignal, manual: boolean): Promise<ReadyProbe | null> => {
      if (!canRequest(manual)) return null;
      try {
        let result = await requestSessionVisualProbe(sid, kind, "entry", signal);
        if (!current(token, signal)) return null;
        for (let retry = 0; result.status === "conflict" && retry < SESSION_VISUAL.CONFLICT_RETRIES; retry += 1) {
          if (!canRequest(manual)) {
            entryFailure(`${messages.conflict}: ${result.error}`);
            return null;
          }
          result = await requestSessionVisualProbe(sid, kind, "entry", signal);
          if (!current(token, signal)) return null;
        }
        if (result.status === "conflict") {
          entryFailure(`${messages.conflict}: ${result.error}`);
          return null;
        }
        if (result.status === "missing" || result.status === "forbidden") {
          directoryVersion = null;
          directoryOutcome = "idle";
          nextDirectoryAt = 0;
          publish({
            status: result.status === "missing" ? "missing" : "error",
            finalUrl: null, version: null,
            error: result.status === "forbidden" ? `${messages.accessDenied}: ${result.error}` : null,
            updateStatus: "idle", updateError: null,
          });
          if (result.status === "forbidden") nextChainAt = performance.now() + SESSION_VISUAL.POLL_MS;
          return null;
        }
        const identityChanged = snapshot.finalUrl !== result.finalUrl || snapshot.version !== result.version;
        const wasAvailable = snapshot.finalUrl !== null;
        if (identityChanged) {
          directoryVersion = null;
          directoryOutcome = "idle";
          nextDirectoryAt = 0;
        }
        publish({
          status: "ready", finalUrl: result.finalUrl, version: result.version, error: null,
          reloadKey: snapshot.reloadKey + (wasAvailable && identityChanged ? 1 : 0),
          ...(identityChanged ? { updateStatus: "idle" as const, updateError: null } : {}),
        });
        return result;
      } catch (error) {
        if (current(token, signal)) entryFailure(`${messages.entryError}: ${errorMessage(error)}`);
        return null;
      }
    };

    const arm = (at: number) => {
      clearTimer();
      if (!alive || document.visibilityState === "hidden") return;
      timer = window.setTimeout(() => {
        timer = null;
        void run(false);
      }, Math.max(0, at - performance.now()));
    };

    const run = async (manual: boolean) => {
      if (!alive || inFlight) return;
      if (!manual && document.visibilityState === "hidden") {
        pending = true;
        return;
      }
      if (!manual && performance.now() < nextChainAt) {
        arm(nextChainAt);
        return;
      }
      clearTimer();
      clearDebounce();
      pending = false;
      inFlight = true;
      const token = ++generation;
      const requestController = new AbortController();
      controller = requestController;
      const { signal } = requestController;
      try {
        const previousReload = snapshot.reloadKey;
        const entry = await readEntry(token, signal, manual);
        if (!current(token, signal) || !entry) return;
        if (manual && snapshot.reloadKey === previousReload) {
          publish({ reloadKey: snapshot.reloadKey + 1 });
        }
        if (kind === "stage") {
          publish({ updateStatus: "ready", updateError: null });
          return;
        }
        if ((!manual && document.visibilityState === "hidden") || performance.now() < nextDirectoryAt) return;
        publish({ updateStatus: "checking" });
        let result: SessionVisualProbeResult;
        try {
          result = await requestSessionVisualProbe(sid, kind, "1", signal);
        } catch (error) {
          if (current(token, signal)) directoryFailure(errorMessage(error));
          return;
        }
        if (!current(token, signal)) return;
        if (snapshot.finalUrl !== entry.finalUrl || snapshot.version !== entry.version) return;
        if (result.status !== "ready" || result.finalUrl !== entry.finalUrl) {
          directoryFailure(messages.sourceChanged);
          // Revalidation is terminal: never enter the directory stage again in this chain.
          await readEntry(token, signal, manual);
          if (!current(token, signal)) return;
          nextDirectoryAt = performance.now() + SESSION_VISUAL.RETRY_MS;
          nextChainAt = performance.now() + SESSION_VISUAL.POLL_MS;
          if (snapshot.finalUrl) {
            directoryOutcome = "error";
            publish({ updateStatus: "error", updateError: messages.sourceChanged });
          }
          return;
        }
        const reload = directoryVersion === null || directoryVersion !== result.version || directoryOutcome === "error";
        // Commit the complete baseline before refreshing; entry loading may precede this sample.
        directoryVersion = result.version;
        directoryOutcome = "ready";
        nextDirectoryAt = 0;
        publish({
          updateStatus: "ready", updateError: null,
          reloadKey: snapshot.reloadKey + (reload ? 1 : 0),
        });
      } finally {
        if (current(token, signal)) {
          inFlight = false;
          controller = null;
          const at = pending ? performance.now() : performance.now() + SESSION_VISUAL.POLL_MS;
          arm(Math.max(at, nextChainAt));
        }
      }
    };

    const queue = () => {
      pending = true;
      if (!inFlight) arm(Math.max(performance.now(), nextChainAt));
    };
    const scheduleEvent = () => {
      clearDebounce();
      if (document.visibilityState === "hidden") {
        pending = true;
        return;
      }
      debounce = window.setTimeout(() => {
        debounce = null;
        queue();
      }, SESSION_VISUAL_LAYOUT[kind].debounceMs);
    };
    const handle = (event: AgentspaceEvent) => {
      if (event.kind === "resync") {
        scheduleEvent();
        return;
      }
      if (["watcher_error", "locks", "trash_changed"].includes(event.kind)) return;
      const target = targetRoot(snapshot.finalUrl);
      if (event.path === metaPath || event.new_path === metaPath
        || matchesResourcePath(event.path, sourceRoot) || matchesResourcePath(event.new_path, sourceRoot)
        || (target !== null && (matchesResourcePath(event.path, target) || matchesResourcePath(event.new_path, target)))) {
        scheduleEvent();
      }
    };
    const visibilityChanged = () => {
      if (document.visibilityState === "hidden") {
        clearTimer();
        clearDebounce();
        pending = true;
      } else {
        queue();
      }
    };
    const manualRefresh = () => {
      ++generation;
      controller?.abort();
      controller = null;
      inFlight = false;
      clearTimer();
      clearDebounce();
      nextChainAt = 0;
      nextDirectoryAt = 0;
      if (snapshot.updateStatus === "checking") publish({ updateStatus: directoryOutcome });
      void run(true);
    };
    refreshRef.current = { scope, run: manualRefresh };
    const unsubscribe = subscribeChatAgentspaceEvents(handle);
    document.addEventListener("visibilitychange", visibilityChanged);
    void run(false);
    return () => {
      alive = false;
      ++generation;
      controller?.abort();
      clearTimer();
      clearDebounce();
      unsubscribe();
      document.removeEventListener("visibilitychange", visibilityChanged);
      if (refreshRef.current?.run === manualRefresh) refreshRef.current = null;
    };
  }, [scope, sessionId, kind, paused]);

  const value = owned.scope === scope ? owned.value : emptySnapshot(paused || !!sessionId);
  return { ...value, refresh };
}
