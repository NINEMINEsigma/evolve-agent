import { useCallback, useState } from "react";
import { SubagentSession, WSMessage } from "../types";

export interface SubagentManager {
  subagentSessionsMap: Record<string, Record<string, SubagentSession>>;
  setSubagentSessionsMap: React.Dispatch<React.SetStateAction<Record<string, Record<string, SubagentSession>>>>;
  subagentIdleCountdown: number | null;
  setSubagentIdleCountdown: React.Dispatch<React.SetStateAction<number | null>>;
  handleMessage: (msg: WSMessage, currentSessionId: string) => void;
  mergeSnapshot: (sid: string, data: { subagents?: Record<string, SubagentSession> }) => void;
}

export function useSubagentManager(): SubagentManager {
  const [subagentSessionsMap, setSubagentSessionsMap] = useState<Record<string, Record<string, SubagentSession>>>({});
  const [subagentIdleCountdown, setSubagentIdleCountdown] = useState<number | null>(null);

  const mergeSnapshot = useCallback((sid: string, data: { subagents?: Record<string, SubagentSession> }) => {
    if (!data.subagents) return;
    setSubagentSessionsMap((prevMap) => {
      const incoming = data.subagents as Record<string, SubagentSession>;
      const prev = prevMap[sid] || {};
      const merged: Record<string, SubagentSession> = {};
      for (const [sKey, snap] of Object.entries(incoming)) {
        const existing = prev[sKey];
        if (!existing) {
          merged[sKey] = snap;
          continue;
        }
        const snapIds = new Set(
          (snap.feedback || []).map((f) => `${f.role}::${f.content?.slice(0, 80)}::${f.tool_call_id || ""}`)
        );
        const wsOnly = (existing.feedback || []).filter(
          (f) => !snapIds.has(`${f.role}::${f.content?.slice(0, 80)}::${f.tool_call_id || ""}`)
        );
        merged[sKey] = {
          ...snap,
          feedback: [...(snap.feedback || []), ...wsOnly],
          pending_approvals: existing.pending_approvals?.length ? existing.pending_approvals : snap.pending_approvals,
        };
      }
      for (const sKey of Object.keys(prev)) {
        if (!(sKey in incoming)) {
          delete merged[sKey];
        }
      }
      return { ...prevMap, [sid]: merged };
    });
  }, []);

  const handleMessage = useCallback((msg: WSMessage, currentSessionId: string) => {
    if (msg.type !== "subagent_update") return;
    const raw = msg.result ?? "";
    try {
      const data = JSON.parse(raw);
      const subId = data.session_id || "";
      const parentId = msg.session_id || currentSessionId;
      const rawFeedback = Array.isArray(data.feedback) ? data.feedback : [];
      for (const item of rawFeedback) {
        if (item.role === "countdown") {
          const v = parseInt(item.content, 10);
          if (!isNaN(v)) {
            setSubagentIdleCountdown(v);
          }
          break;
        }
      }
      setSubagentSessionsMap((prevMap) => {
        const prev = prevMap[parentId] || {};
        if (data._removed) {
          const next = { ...prev };
          delete next[subId];
          const nextMap = { ...prevMap, [parentId]: next };
          if (Object.keys(next).length === 0 && parentId === currentSessionId) {
            setSubagentIdleCountdown(null);
          }
          return nextMap;
        }
        const existing = prev[subId];
        const prevFeedback = existing?.feedback || [];
        const prevApprovals = existing?.pending_approvals || [];
        const realFeedback: Array<{
          role: string;
          content: string;
          tool_name?: string;
          tool_call_id?: string;
          tool_args?: Record<string, unknown>;
          reasoning?: string;
        }> = [];
        for (const item of rawFeedback) {
          if (item.role === "countdown") continue;
          if (item.role === "status" && !item.content) continue;
          realFeedback.push(item);
        }
        const newApprovals = Array.isArray(data.pending_approvals) ? data.pending_approvals : [];
        return {
          ...prevMap,
          [parentId]: {
            ...prev,
            [subId]: {
              session_id: subId,
              name: data.name || existing?.name || "",
              status: data.status || existing?.status || "running",
              feedback: [...prevFeedback, ...realFeedback],
              pending_approvals: data.pending_approvals !== undefined ? newApprovals : prevApprovals,
            },
          },
        };
      });
    } catch {}
  }, []);

  return {
    subagentSessionsMap,
    setSubagentSessionsMap,
    subagentIdleCountdown,
    setSubagentIdleCountdown,
    handleMessage,
    mergeSnapshot,
  };
}