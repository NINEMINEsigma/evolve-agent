import type { SessionRuntimeStatus } from "../../types";

export async function fetchMainSessionStatus(
  sessionId: string,
  signal: AbortSignal,
): Promise<SessionRuntimeStatus> {
  const response = await fetch(
    `/api/sessions/${encodeURIComponent(sessionId)}/status`,
    { signal, cache: "no-store" },
  );
  if (!response.ok) {
    throw new Error(`Main session activity request failed: HTTP ${response.status}`);
  }
  const status = await response.json() as SessionRuntimeStatus;
  if (status.session_id !== sessionId) {
    throw new Error("Main session activity response does not match the current session");
  }
  return status;
}
