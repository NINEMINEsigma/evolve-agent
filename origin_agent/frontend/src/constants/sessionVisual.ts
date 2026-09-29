import type { SessionVisualKind } from "../types/sessionVisual";

/** 与 entity/constant/session_visual.py 的协议字段保持一致。 */
export const SESSION_VISUAL = {
  RAW_PARAM: "visual_raw",
  PROBE_PARAM: "visual_probe",
  SID_PARAM: "visual_sid",
  KIND_PARAM: "visual_kind",
  ENABLED: "1",
  VERSION_HEADER: "X-Session-Visual-Version",
  FILES_PREFIX: "/files/",
  ZIP_PREFIX: "/zip/",
  META_SUFFIX: ".meta",
  // 普通轮询、失败重试和单请求截止，单位毫秒。
  POLL_MS: 5000,
  RETRY_MS: 15000,
  TIMEOUT_MS: 15000,
  CONFLICT_RETRIES: 1,
} as const;

export const SESSION_VISUAL_LAYOUT: Record<SessionVisualKind, {
  directory: string;
  entry: string;
  debounceMs: number;
}> = {
  stage: { directory: "stage", entry: "index.html", debounceMs: 1000 },
  site: { directory: "site", entry: "index.html", debounceMs: 1000 },
  chat_style: { directory: "chat-style", entry: "index.css", debounceMs: 300 },
};
