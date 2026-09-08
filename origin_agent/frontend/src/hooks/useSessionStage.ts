/**
 * 会话舞台层状态 hook。
 *
 * 探测当前会话的 stage/index.html 是否存在，并通过 Agentspace SSE
 * 监听 stage/ 目录的文件变化，自动刷新 iframe。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { buildStageUrls } from "../utils";
import { connectAgentspaceEvents } from "../services/agentspaceApi";
import type { AgentspaceEvent } from "../types";

export type StageStatus = "idle" | "missing" | "ready";

export interface SessionStageState {
  status: StageStatus;
  reloadKey: number;
  stageUrl: string | null;
}

const DEBOUNCE_MS = 300;

export function useSessionStage(sessionId: string | undefined): SessionStageState {
  const [status, setStatus] = useState<StageStatus>("idle");
  const [reloadKey, setReloadKey] = useState(0);
  const [stageUrl, setStageUrl] = useState<string | null>(null);

  const urls = sessionId ? buildStageUrls(sessionId) : null;
  const probeSeqRef = useRef(0);
  const debounceTimerRef = useRef<number | null>(null);
  const stagePathPrefixRef = useRef<string>("");

  const probe = useCallback(async () => {
    if (!urls) {
      setStatus("missing");
      setStageUrl(null);
      return;
    }
    const seq = ++probeSeqRef.current;
    try {
      const resp = await fetch(urls.indexUrl, { cache: "no-store" });
      if (seq !== probeSeqRef.current) return;
      if (resp.ok) {
        setStatus("ready");
        setStageUrl(urls.indexUrl);
      } else {
        setStatus("missing");
        setStageUrl(null);
      }
    } catch {
      if (seq !== probeSeqRef.current) return;
      setStatus("missing");
      setStageUrl(null);
    }
  }, [urls]);

  // 会话切换：重置状态并重新探测
  useEffect(() => {
    setStatus("idle");
    setReloadKey(0);
    setStageUrl(null);
    // Agentspace 事件的 path 不带 ws: 前缀，是相对于工作空间根的路径
    // 例如 "sessions/<sid>/stage/index.html"
    stagePathPrefixRef.current = sessionId
      ? `sessions/${sessionId}/stage/`
      : "";
    if (sessionId) {
      probe();
    } else {
      setStatus("missing");
    }
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  // SSE 监听 stage/ 目录变化
  useEffect(() => {
    if (!sessionId) return;

    const prefix = stagePathPrefixRef.current;
    if (!prefix) return;

    const isStagePath = (path: string | null): boolean => {
      if (!path) return false;
      return path.startsWith(prefix);
    };

    const handleEvent = (event: AgentspaceEvent) => {
      // resync：重新探测
      if (event.kind === "resync") {
        probe();
        return;
      }

      // watcher_error：不改变当前状态，仅停止自动刷新
      if (event.kind === "watcher_error") {
        return;
      }

      // 只关注 stage/ 路径的文件事件
      if (!isStagePath(event.path) && !isStagePath(event.new_path)) {
        return;
      }

      // deleted：检查是否删除了 index.html 或整个 stage/ 目录
      if (event.kind === "deleted") {
        const isIndexHtml = event.path === `${prefix}index.html`;
        const isStageDir = event.is_directory === true && event.path === prefix.slice(0, -1);
        if (isIndexHtml || isStageDir) {
          setStatus("missing");
          setStageUrl(null);
          return;
        }
        // 删除其他文件也可能影响引用资源，debounce 刷新
      }

      // created / modified / moved / deleted(非关键) ：debounce 后刷新
      if (debounceTimerRef.current != null) {
        window.clearTimeout(debounceTimerRef.current);
      }
      debounceTimerRef.current = window.setTimeout(() => {
        debounceTimerRef.current = null;
        setReloadKey((k) => k + 1);
        probe();
      }, DEBOUNCE_MS);
    };

    const cleanup = connectAgentspaceEvents(handleEvent, () => {});

    return () => {
      cleanup();
      if (debounceTimerRef.current != null) {
        window.clearTimeout(debounceTimerRef.current);
        debounceTimerRef.current = null;
      }
    };
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  return { status, reloadKey, stageUrl };
}
