/**
 * Right-tab hover preview parameters, geometry limits and Chinese copy.
 * Text lives in tabPreviewLabels.json (a data resource); this module only
 * exposes typed, explicitly-read fields plus numeric constants.
 */
import data from "../features/tabs/tabPreviewLabels.json";

export interface TabPreviewLabels {
  chatStatus: string;
  pendingProfile: string;
  images: string;
  files: string;
  shells: string;
  runningShells: string;
  cronTasks: string;
  scheduledCronTasks: string;
  dynamicEndpoints: string;
  subagents: string;
  running: string;
  completed: string;
  terminated: string;
  characters: string;
  available: string;
  unavailable: string;
  roleplay: string;
  task: string;
  siteStatus: string;
  siteUrl: string;
  llmProfiles: string;
  approvalProfile: string;
  metadataProfile: string;
  sandboxSpaces: string;
  readonlySpaces: string;
  writableSpaces: string;
  notLoaded: string;
  loading: string;
  readFailed: string;
  cachedSnapshot: string;
  noProfile: string;
  noScheduledTask: string;
  duePending: string;
  previewUnavailable: string;
  cronEvent: string;
  waitEvent: string;
  triggerAt: string;
  remaining: string;
  reminder: string;
  archived: string;
  busy: string;
  idle: string;
  unknown: string;
  openTabHint: string;
  mediaEnabled: string;
  mediaDisabled: string;
  inlinePayloadChars: string;
  unknownPayload: string;
  mediaEmpty: string;
  mediaNotLoaded: string;
  variables: string;
  variableCount: string;
  variableNumbers: string;
  variableStrings: string;
  variableInvalid: string;
  variableIssues: string;
  variablesNotLoaded: string;
  variablesLoading: string;
  scanIncomplete: string;
  variablesEmpty: string;
}

function text(value: unknown): string {
  if (typeof value !== "string" || !value) throw new Error("Invalid tab preview language resource text");
  return value;
}

// 中文文案属于正式 JSON 数据资源；源代码标识保持英文，资源缺字段快速失败。
export const TAB_PREVIEW_LABELS: TabPreviewLabels = {
  chatStatus: text(data.chatStatus), pendingProfile: text(data.pendingProfile),
  images: text(data.images), files: text(data.files), shells: text(data.shells),
  runningShells: text(data.runningShells), cronTasks: text(data.cronTasks),
  scheduledCronTasks: text(data.scheduledCronTasks), dynamicEndpoints: text(data.dynamicEndpoints),
  subagents: text(data.subagents), running: text(data.running), completed: text(data.completed),
  terminated: text(data.terminated), characters: text(data.characters), available: text(data.available),
  unavailable: text(data.unavailable), roleplay: text(data.roleplay), task: text(data.task),
  siteStatus: text(data.siteStatus), siteUrl: text(data.siteUrl), llmProfiles: text(data.llmProfiles),
  approvalProfile: text(data.approvalProfile), metadataProfile: text(data.metadataProfile),
  sandboxSpaces: text(data.sandboxSpaces), readonlySpaces: text(data.readonlySpaces),
  writableSpaces: text(data.writableSpaces), notLoaded: text(data.notLoaded), loading: text(data.loading),
  readFailed: text(data.readFailed), cachedSnapshot: text(data.cachedSnapshot), noProfile: text(data.noProfile),
  noScheduledTask: text(data.noScheduledTask), duePending: text(data.duePending),
  previewUnavailable: text(data.previewUnavailable), cronEvent: text(data.cronEvent),
  waitEvent: text(data.waitEvent), triggerAt: text(data.triggerAt), remaining: text(data.remaining),
  reminder: text(data.reminder), archived: text(data.archived), busy: text(data.busy), idle: text(data.idle),
  unknown: text(data.unknown), openTabHint: text(data.openTabHint), mediaEnabled: text(data.mediaEnabled),
  mediaDisabled: text(data.mediaDisabled), inlinePayloadChars: text(data.inlinePayloadChars),
  unknownPayload: text(data.unknownPayload), mediaEmpty: text(data.mediaEmpty),
  mediaNotLoaded: text(data.mediaNotLoaded), variables: text(data.variables),
  variableCount: text(data.variableCount), variableNumbers: text(data.variableNumbers),
  variableStrings: text(data.variableStrings), variableInvalid: text(data.variableInvalid),
  variableIssues: text(data.variableIssues), variablesNotLoaded: text(data.variablesNotLoaded),
  variablesLoading: text(data.variablesLoading), scanIncomplete: text(data.scanIncomplete),
  variablesEmpty: text(data.variablesEmpty),
};

export const TAB_PREVIEW = {
  SHOW_DELAY_MS: 250,
  HIDE_DELAY_MS: 120,
  WIDTH_PX: 320,
  MAX_HEIGHT_PX: 480,
  GAP_PX: 8,
  VIEWPORT_MARGIN_PX: 8,
  REMINDER_MAX_CHARS: 120,
  TEXT_MAX_CHARS: 160,
  MODAL_SELECTOR: '[aria-modal="true"]',
} as const;