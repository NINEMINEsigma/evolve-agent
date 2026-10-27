export const PREVIEW = {
  storagePrefix: "evolve_preview_v1:",
  timestamp: "2026-10-27T02:30:00.000+00:00",
  epochMs: 1793068200000,
  defaultProfile: "Evolve · Main",
  mainSession: "preview-main",
  emptySession: "preview-empty",
  multiSession: "preview-multi",
  archivedSession: "preview-archived",
  approvalSession: "preview-approval",
  questionSession: "preview-question",
  prepareTimeoutMs: 10000,
  chunkDelayMs: 45,
  chunkChars: 14,
  maxFaults: 20,
  defaultMaxTurns: 90,
  version: "preview-v1",
} as const;

export const DEMO_ASSETS = {
  cover: "/demo/cover.svg", diagram: "/demo/diagram.svg",
  site: "/demo/site/index.html", stage: "/demo/stage/index.html",
  chatStyle: "/demo/chat-style/index.css",
} as const;
export const PREVIEW_MEDIA_URLS = new Map<string, string>();

export const TAB_IDS = ["chat", "activity", "resources", "changes", "media", "variables", "subagents", "characters", "site", "llm", "sandbox"] as const;
