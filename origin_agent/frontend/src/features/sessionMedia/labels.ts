import raw from "./zh-CN.json?raw";
import type { MediaRole, MediaType } from "./types";

interface MediaInputLabels {
  title: string;
  detailsTitle: string;
  count: string;
  refresh: string;
  refreshing: string;
  previous: string;
  next: string;
  pagination: string;
  range: string;
  noLoadedItems: string;
  close: string;
  loading: string;
  waitingUpdates: string;
  empty: string;
  shortNote: string;
  archived: string;
  readFailed: string;
  stale: string;
  confirming: string;
  settingsDisabled: string;
  errorDetails: string;
  saveFailed: string;
  unknownSave: string;
  previewLoading: string;
  previewFailed: string;
  previewUnavailable: string;
  audioPreview: string;
  videoPreview: string;
  unnamed: string;
  openDetails: string;
  imageAlt: string;
  enabled: string;
  disabled: string;
  saving: string;
  needsAttention: string;
  sendLabel: string;
  sendDescription: string;
  forwardingNote: string;
  timingNote: string;
  identity: string;
  source: string;
  unknownSource: string;
  character: string;
  messageType: string;
  historyLocation: string;
  historyLocationValue: string;
  toolCall: string;
  mimeType: string;
  inlineSize: string;
  inlineSizeValue: string;
  remoteMedia: string;
  descriptionCache: string;
  cached: string;
  notCached: string;
  mediaTypes: Record<MediaType, string>;
  roles: Record<MediaRole, string>;
}

function object(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Invalid media input language resource object");
  }
  return value as Record<string, unknown>;
}

function text(value: unknown): string {
  if (typeof value !== "string" || !value) throw new Error("Invalid media input language resource text");
  return value;
}

// 中文文案属于正式JSON数据资源；源代码标识保持英文，资源缺字段快速失败。
const data = object(JSON.parse(raw) as unknown);
const mediaTypes = object(data.mediaTypes);
const roles = object(data.roles);
export const mediaInputLabels: MediaInputLabels = {
  title: text(data.title), detailsTitle: text(data.detailsTitle), count: text(data.count),
  refresh: text(data.refresh), refreshing: text(data.refreshing), previous: text(data.previous),
  next: text(data.next), pagination: text(data.pagination), range: text(data.range),
  noLoadedItems: text(data.noLoadedItems), close: text(data.close), loading: text(data.loading),
  waitingUpdates: text(data.waitingUpdates), empty: text(data.empty), shortNote: text(data.shortNote),
  archived: text(data.archived), readFailed: text(data.readFailed), stale: text(data.stale),
  confirming: text(data.confirming), settingsDisabled: text(data.settingsDisabled), errorDetails: text(data.errorDetails), saveFailed: text(data.saveFailed),
  unknownSave: text(data.unknownSave), previewLoading: text(data.previewLoading), previewFailed: text(data.previewFailed),
  previewUnavailable: text(data.previewUnavailable), audioPreview: text(data.audioPreview), videoPreview: text(data.videoPreview),
  unnamed: text(data.unnamed), openDetails: text(data.openDetails), imageAlt: text(data.imageAlt),
  enabled: text(data.enabled), disabled: text(data.disabled), saving: text(data.saving), needsAttention: text(data.needsAttention),
  sendLabel: text(data.sendLabel), sendDescription: text(data.sendDescription), forwardingNote: text(data.forwardingNote),
  timingNote: text(data.timingNote), identity: text(data.identity), source: text(data.source),
  unknownSource: text(data.unknownSource), character: text(data.character), messageType: text(data.messageType),
  historyLocation: text(data.historyLocation), historyLocationValue: text(data.historyLocationValue),
  toolCall: text(data.toolCall), mimeType: text(data.mimeType), inlineSize: text(data.inlineSize),
  inlineSizeValue: text(data.inlineSizeValue), remoteMedia: text(data.remoteMedia), descriptionCache: text(data.descriptionCache),
  cached: text(data.cached), notCached: text(data.notCached),
  mediaTypes: { image: text(mediaTypes.image), audio: text(mediaTypes.audio), video: text(mediaTypes.video) },
  roles: { user: text(roles.user), assistant: text(roles.assistant), system: text(roles.system), tool: text(roles.tool) },
};

export function formatMediaLabel(template: string, values: Record<string, string | number>): string {
  let result = template;
  for (const [key, value] of Object.entries(values)) result = result.split(`{{${key}}}`).join(String(value));
  return result;
}
