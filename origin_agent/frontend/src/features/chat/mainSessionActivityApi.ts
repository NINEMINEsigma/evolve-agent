import type { SessionRuntimeStatus } from "../../types";
import { TIMING } from "../../constants/timing";
import { fetchJsonWithTimeout } from "../../services/fetchJsonWithTimeout";

export async function fetchMainSessionStatus(
  sessionId: string,
  signal: AbortSignal,
): Promise<SessionRuntimeStatus> {
  return fetchJsonWithTimeout(`/api/sessions/${encodeURIComponent(sessionId)}/status`, { signal },
    { timeoutMs: TIMING.CRITICAL_REQUEST_TIMEOUT, phase: "main-session-activity" }, (value) => {
      if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid main session status response");
      const status = value as Record<string, unknown>;
      if (status.session_id !== sessionId || typeof status.exists !== "boolean"
        || typeof status.occupied !== "boolean" || typeof status.processing !== "boolean") {
        throw new Error("Main session activity response does not match the current session");
      }
      if (status.activity !== undefined && status.activity !== null) {
        if (typeof status.activity !== "object" || Array.isArray(status.activity)) throw new Error("Invalid main session activity snapshot");
        const activity = status.activity as Record<string, unknown>;
        if (typeof activity.activity_id !== "string" || !activity.activity_id || !Number.isSafeInteger(activity.revision)
          || (activity.revision as number) < 0
          || !["user_message", "dynamic_endpoint", "subagent_feedback", "cron", "regenerate", "resume", "other", "mixed"].includes(String(activity.source))
          || !["queued", "preparing", "waiting_first_token", "streaming", "waiting_approval", "waiting_tool"].includes(String(activity.phase))
          || (activity.stream_id !== undefined && activity.stream_id !== null && typeof activity.stream_id !== "string")
          || (activity.character_name !== undefined && activity.character_name !== null && typeof activity.character_name !== "string")) throw new Error("Invalid main session activity snapshot");
      }
      return value as SessionRuntimeStatus;
    });
}
