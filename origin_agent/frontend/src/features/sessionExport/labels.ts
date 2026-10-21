import text from "./zh-CN.json";

export const exportLabels = {
  title: text.title, start: text.start, cancel: text.cancel, close: text.close,
  scope: text.scope, privacy: text.privacy, limitations: text.limitations,
  offline: text.offline, idle: text.idle, capturing: text.capturing,
  collecting: text.collecting, packing: text.packing, verifying: text.verifying,
  succeeded: text.succeeded, failed: text.failed, cancelled: text.cancelled,
  unavailable: text.unavailable, issues: text.issues, source: text.source,
  stage: text.stage, chatStyle: text.chatStyle, pause: text.pause, enable: text.enable,
  copyFailed: text.copyFailed, diagramFailed: text.diagramFailed,
  frameOpen: text.frameOpen, attachment: text.attachment, busy: text.busy,
  changed: text.changed, readme: text.readme,
  expand: text.expand, collapse: text.collapse,
  backendUnavailable: text.backendUnavailable,
  cssSyntax: text.cssSyntax, cssImport: text.cssImport, cssFontPrefix: text.cssFontPrefix, cssRule: text.cssRule,
  applied: text.applied, approval: text.approval, invocation: text.invocation,
};
for (const value of Object.values(exportLabels)) {
  if (typeof value !== "string" || !value) throw new Error("Invalid export labels");
}
