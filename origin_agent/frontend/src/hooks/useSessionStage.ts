/**
 * 会话舞台层状态 hook。
 *
 * 探测当前会话的 stage/index.html，并把该入口文件视为一次舞台部署的
 * 提交标记：资源文件可以批量写入，只有 index.html 新版本到达时才重建 iframe。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { buildStageUrls } from "../utils";
import { connectAgentspaceEvents } from "../services/agentspaceApi";
import type { AgentspaceEvent } from "../types";
import { chatTelemetry } from "../features/chat/chatTelemetry";

export type StageStatus = "idle" | "missing" | "ready";

export interface SessionStageState {
  status: StageStatus;
  reloadKey: number;
  stageUrl: string | null;
}

// index.html 可能紧随一批资源写入；安静窗口内只应用最后一个入口版本。
const STAGE_COMMIT_DEBOUNCE_MS = 1000;

interface ProbeOptions {
  preserveReady?: boolean;
}

export function useSessionStage(
  sessionId: string | undefined,
  paused: boolean = false,
): SessionStageState {
  const [status, setStatus] = useState<StageStatus>("idle");
  const [reloadKey, setReloadKey] = useState(0);
  const [stageUrl, setStageUrl] = useState<string | null>(null);

  const urls = useMemo(
    () => sessionId && !paused ? buildStageUrls(sessionId) : null,
    [sessionId, paused],
  );
  const stageRoot = sessionId ? `sessions/${sessionId}/stage` : "";
  const stagePrefix = stageRoot ? `${stageRoot}/` : "";
  const indexPath = stagePrefix ? `${stagePrefix}index.html` : "";
  const probeSeqRef = useRef(0);
  const commitSeqRef = useRef(0);
  const debounceTimerRef = useRef<number | null>(null);
  const pendingRevisionRef = useRef<string | null>(null);
  const lastAppliedRevisionRef = useRef<string | null>(null);

  const clearPendingCommit = useCallback(() => {
    if (debounceTimerRef.current !== null) {
      window.clearTimeout(debounceTimerRef.current);
      debounceTimerRef.current = null;
    }
    pendingRevisionRef.current = null;
  }, []);

  const probe = useCallback(async (
    options: ProbeOptions = {},
  ): Promise<boolean> => {
    if (!urls) {
      if (!options.preserveReady) {
        setStatus("missing");
        setStageUrl(null);
      }
      return false;
    }
    const seq = ++probeSeqRef.current;
    const started = performance.now();
    try {
      const response = await fetch(urls.indexUrl, { cache: "no-store" });
      chatTelemetry.record({
        time: Date.now(),
        kind: "stage_probe",
        durationMs: performance.now() - started,
        status: response.status,
      });
      if (seq !== probeSeqRef.current) return false;
      if (!response.ok) {
        if (!options.preserveReady) {
          setStatus("missing");
          setStageUrl(null);
        }
        return false;
      }
      setStatus("ready");
      setStageUrl(urls.indexUrl);
      return true;
    } catch {
      chatTelemetry.record({
        time: Date.now(),
        kind: "stage_probe",
        durationMs: performance.now() - started,
        status: 0,
      });
      if (seq !== probeSeqRef.current) return false;
      // SSE 重连或暂时性请求失败不应卸载一个已经正常运行的舞台。
      if (!options.preserveReady) {
        setStatus("missing");
        setStageUrl(null);
      }
      return false;
    }
  }, [urls]);

  useEffect(() => {
    ++probeSeqRef.current;
    ++commitSeqRef.current;
    clearPendingCommit();
    lastAppliedRevisionRef.current = null;
    setReloadKey(0);

    if (paused || !sessionId || !urls) {
      setStatus("missing");
      setStageUrl(null);
      return;
    }

    setStatus("idle");
    setStageUrl(null);
    void probe();

    return () => {
      ++probeSeqRef.current;
      ++commitSeqRef.current;
      clearPendingCommit();
    };
  }, [sessionId, paused, urls, probe, clearPendingCommit]);

  useEffect(() => {
    if (!sessionId || paused || !stagePrefix || !indexPath) return;

    const isStagePath = (path: string | null): boolean => (
      path === stageRoot || !!path?.startsWith(stagePrefix)
    );

    const markMissing = () => {
      ++commitSeqRef.current;
      clearPendingCommit();
      ++probeSeqRef.current;
      lastAppliedRevisionRef.current = null;
      setStatus("missing");
      setStageUrl(null);
    };

    const scheduleCommittedReload = (event: AgentspaceEvent) => {
      const revision = event.version
        || event.operation_id
        || `${event.kind}:${event.sequence}`;
      if (
        revision === lastAppliedRevisionRef.current
        || revision === pendingRevisionRef.current
      ) return;

      clearPendingCommit();
      const commitSeq = ++commitSeqRef.current;
      pendingRevisionRef.current = revision;
      debounceTimerRef.current = window.setTimeout(() => {
        debounceTimerRef.current = null;
        const pendingRevision = pendingRevisionRef.current;
        pendingRevisionRef.current = null;
        if (!pendingRevision || pendingRevision === lastAppliedRevisionRef.current) return;
        void probe({ preserveReady: true }).then((exists) => {
          if (
            commitSeq !== commitSeqRef.current
            || !exists
            || pendingRevision === lastAppliedRevisionRef.current
          ) return;
          lastAppliedRevisionRef.current = pendingRevision;
          setReloadKey((key) => key + 1);
          chatTelemetry.record({
            time: Date.now(),
            kind: "stage_reload",
            count: 1,
          });
        });
      }, STAGE_COMMIT_DEBOUNCE_MS);
    };

    const handleEvent = (event: AgentspaceEvent) => {
      if (event.kind === "resync") {
        // 重连只校验入口存在性；不得重建正在运行的 iframe。
        void probe({ preserveReady: true });
        return;
      }
      if (
        event.kind === "watcher_error"
        || event.kind === "locks"
        || event.kind === "trash_changed"
      ) return;
      if (!isStagePath(event.path) && !isStagePath(event.new_path)) return;

      if (event.kind === "deleted") {
        const deletedIndex = event.path === indexPath;
        const deletedRoot = event.is_directory === true && event.path === stageRoot;
        if (deletedIndex || deletedRoot) {
          markMissing();
        }
        // 非入口资源删除不重建 iframe；由下一次 index.html 提交统一应用。
        return;
      }

      if (event.kind === "moved") {
        const movedIndexAway = event.path === indexPath && event.new_path !== indexPath;
        const movedRootAway = (
          event.is_directory === true
          && event.path === stageRoot
          && event.new_path !== stageRoot
        );
        if (movedIndexAway || movedRootAway) {
          markMissing();
          return;
        }
      }

      const entryCommitted = (
        (event.kind === "created" || event.kind === "modified")
        && event.path === indexPath
      ) || (event.kind === "moved" && event.new_path === indexPath);

      if (entryCommitted) scheduleCommittedReload(event);
      // 其他 stage/ 资源事件只标记了一次部署的中间步骤，不刷新 iframe。
    };

    const cleanup = connectAgentspaceEvents(handleEvent, () => {});
    return () => {
      ++commitSeqRef.current;
      cleanup();
      clearPendingCommit();
    };
  }, [
    sessionId,
    paused,
    stageRoot,
    stagePrefix,
    indexPath,
    probe,
    clearPendingCommit,
  ]);

  return { status, reloadKey, stageUrl };
}
