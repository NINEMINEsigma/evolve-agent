import { SESSION_VISUAL, SESSION_VISUAL_LAYOUT } from "../constants/sessionVisual";
import type { SessionVisualKind, SessionVisualProbeMode, SessionVisualProbeResult } from "../types/sessionVisual";
import { fetchWithTimeout } from "./fetchWithTimeout";

function stripProbeQuery(raw: string): string {
  const url = new URL(raw, window.location.href);
  for (const name of [SESSION_VISUAL.PROBE_PARAM, SESSION_VISUAL.SID_PARAM, SESSION_VISUAL.KIND_PARAM]) {
    url.searchParams.delete(name);
  }
  return `${url.pathname}${url.search}${url.hash}`;
}

/** Stateless HEAD adapter; polling, retries and ownership belong to the hook. */
export async function requestSessionVisualProbe(
  sessionId: string,
  kind: SessionVisualKind,
  mode: SessionVisualProbeMode,
  signal: AbortSignal,
): Promise<SessionVisualProbeResult> {
  const layout = SESSION_VISUAL_LAYOUT[kind];
  const params = new URLSearchParams({
    [SESSION_VISUAL.PROBE_PARAM]: mode,
    [SESSION_VISUAL.SID_PARAM]: sessionId,
    [SESSION_VISUAL.KIND_PARAM]: kind,
  });
  const url = `${SESSION_VISUAL.FILES_PREFIX}ws/sessions/${encodeURIComponent(sessionId)}/${layout.directory}/${layout.entry}?${params}`;
  const response = await fetchWithTimeout(url, {
    method: "HEAD", cache: "no-store", redirect: "follow", signal,
  }, {
    timeoutMs: SESSION_VISUAL.TIMEOUT_MS,
    phase: `${kind} visual ${mode} probe`,
  });
  if (response.status === 404) return { status: "missing", error: "Visual entry not found (HTTP 404)" };
  if (response.status === 403) return { status: "forbidden", error: "Visual access denied (HTTP 403)" };
  if (response.status === 409) return { status: "conflict", error: "Visual source changed (HTTP 409)" };
  if (response.status !== 200) throw new Error(`Visual ${mode} probe failed (HTTP ${response.status})`);
  const version = response.headers.get(SESSION_VISUAL.VERSION_HEADER);
  if (response.headers.get(SESSION_VISUAL.PROBE_MODE_HEADER) !== mode || !version?.trim()) {
    throw new Error("Invalid visual probe protocol: mode or version header missing");
  }
  return { status: "ready", finalUrl: stripProbeQuery(response.url), version };
}
