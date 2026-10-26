import raw from "./zh-CN.json?raw";

function object(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Invalid agent loop settings language resource");
  }
  return value as Record<string, unknown>;
}

function text(value: unknown): string {
  if (typeof value !== "string" || !value) {
    throw new Error("Missing agent loop settings language resource text");
  }
  return value;
}

// 正式中文资源显式逐字段读取，不将字段缺失伪装为成功。
const data = object(JSON.parse(raw) as unknown);
export const agentLoopSettingsLabels = {
  tabTitle: text(data.tabTitle), title: text(data.title),
  loading: text(data.loading), readFailed: text(data.readFailed),
  save: text(data.save), saving: text(data.saving),
  saved: text(data.saved), restoreDefault: text(data.restoreDefault),
  retry: text(data.retry),
  dirty: text(data.dirty), externalChange: text(data.externalChange),
  validationError: text(data.validationError), saveFailed: text(data.saveFailed),
  unknownSave: text(data.unknownSave), rereadNotice: text(data.rereadNotice),
  requestError: text(data.requestError),
  protocolError: text(data.protocolError), httpError: text(data.httpError),
  errorDetails: text(data.errorDetails), profilesTab: text(data.profilesTab),
  referencesTab: text(data.referencesTab), profileEyebrow: text(data.profileEyebrow),
  tabListLabel: text(data.tabListLabel), editing: text(data.editing),
  editMode: text(data.editMode), saveUncertain: text(data.saveUncertain),
  unsaved: text(data.unsaved), cancel: text(data.cancel), create: text(data.create),
};

export function formatAgentLoopSettingsLabel(
  template: string, values: Record<string, string | number>,
): string {
  let result = template;
  for (const [key, value] of Object.entries(values)) {
    result = result.split(`{{${key}}}`).join(String(value));
  }
  return result;
}
