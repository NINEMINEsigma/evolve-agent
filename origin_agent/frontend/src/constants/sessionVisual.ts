import type { SessionVisualKind } from "../types/sessionVisual";

/** 与 entity/constant/session_visual.py 的协议字段保持一致。 */
export const SESSION_VISUAL = {
  RAW_PARAM: "visual_raw",
  PROBE_PARAM: "visual_probe",
  SID_PARAM: "visual_sid",
  KIND_PARAM: "visual_kind",
  ENABLED: "1",
  VERSION_HEADER: "X-Session-Visual-Version",
  PROBE_MODE_HEADER: "X-Session-Visual-Probe",
  // 与后端过滤集合一致；只过滤即时事件，文件权限和下载不受影响。
  SCAN_IGNORED_NAMES: [".git"] as readonly string[],
  FILES_PREFIX: "/files/",
  ZIP_PREFIX: "/zip/",
  META_SUFFIX: ".meta",
  // 普通轮询按整链结算后计时；目录失败的最短间隔独立控制，单位毫秒。
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
