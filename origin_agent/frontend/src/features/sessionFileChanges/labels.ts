import raw from "./zh-CN.json?raw";
import type { SessionFileChangeAction, SessionFileChangeDisplayState, SessionFileChangeKind } from "./types";

export interface FileChangesLabels {
  title: string;
  summaryFiles: string;
  summaryDirectories: string;
  summaryOperations: string;
  summaryOperationsTooltip: string;
  refresh: string;
  refreshing: string;
  loading: string;
  empty: string;
  treeLoading: string;
  treeReadFailed: string;
  treeLabel: string;
  summaryReadFailed: string;
  pageReadFailed: string;
  requestFailed: string;
  requestTimeout: string;
  protocolError: string;
  stale: string;
  archived: string;
  previous: string;
  next: string;
  pagination: string;
  range: string;
  path: string;
  kind: string;
  lastOperation: string;
  operationCount: string;
  actors: string;
  lastOperatedAt: string;
  moveTooltip: string;
  transferSource: string;
  transferDestination: string;
  actorSeparator: string;
  actorDisambiguated: string;
  operations: Record<SessionFileChangeAction, string>;
  states: Record<SessionFileChangeDisplayState, string>;
  kinds: Record<SessionFileChangeKind, string>;
}

function object(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Invalid file changes language resource object");
  }
  return value as Record<string, unknown>;
}

function text(value: unknown): string {
  if (typeof value !== "string" || !value) throw new Error("Invalid file changes language resource text");
  return value;
}

// 中文文案属于正式JSON数据资源；源代码标识保持英文，资源缺字段快速失败。
const data = object(JSON.parse(raw) as unknown);
const operations = object(data.operations);
const states = object(data.states);
const kinds = object(data.kinds);
export const fileChangesLabels: FileChangesLabels = {
  title: text(data.title),
  summaryFiles: text(data.summaryFiles),
  summaryDirectories: text(data.summaryDirectories),
  summaryOperations: text(data.summaryOperations),
  summaryOperationsTooltip: text(data.summaryOperationsTooltip),
  refresh: text(data.refresh),
  refreshing: text(data.refreshing),
  loading: text(data.loading),
  empty: text(data.empty),
  treeLoading: text(data.treeLoading),
  treeReadFailed: text(data.treeReadFailed),
  treeLabel: text(data.treeLabel),
  summaryReadFailed: text(data.summaryReadFailed),
  pageReadFailed: text(data.pageReadFailed),
  requestFailed: text(data.requestFailed),
  requestTimeout: text(data.requestTimeout),
  protocolError: text(data.protocolError),
  stale: text(data.stale),
  archived: text(data.archived),
  previous: text(data.previous),
  next: text(data.next),
  pagination: text(data.pagination),
  range: text(data.range),
  path: text(data.path),
  kind: text(data.kind),
  lastOperation: text(data.lastOperation),
  operationCount: text(data.operationCount),
  actors: text(data.actors),
  lastOperatedAt: text(data.lastOperatedAt),
  moveTooltip: text(data.moveTooltip),
  transferSource: text(data.transferSource),
  transferDestination: text(data.transferDestination),
  actorSeparator: text(data.actorSeparator),
  actorDisambiguated: text(data.actorDisambiguated),
  operations: {
    create: text(operations.create),
    modify: text(operations.modify),
    delete: text(operations.delete),
    copy: text(operations.copy),
    move: text(operations.move),
  },
  states: {
    created: text(states.created),
    modified: text(states.modified),
    deleted: text(states.deleted),
  },
  kinds: {
    file: text(kinds.file),
    directory: text(kinds.directory),
  },
};

export function formatFileChangesLabel(template: string, values: Record<string, string | number>): string {
  let result = template;
  for (const [key, value] of Object.entries(values)) result = result.split(`{{${key}}}`).join(String(value));
  return result;
}
