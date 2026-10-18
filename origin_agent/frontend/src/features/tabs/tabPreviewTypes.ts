/**
 * Pure summary types for the right-tab hover preview. No React elements, no
 * request methods: selectors only read already-loaded snapshots carried here.
 */
import type {
  CharacterProfileEntryDto,
  CronTask,
  DynamicEndpoint,
  DynamicSandboxSpaceWithAvailability,
  LlmLoadStatus,
  SessionLlmSelectionStatus,
  ShellInfo,
  SubagentSession,
} from "../../types";
import type { SessionResourceSnapshot } from "../../types/sessionResources";
import type { SiteStatus } from "../../hooks/useSessionSite";
import type { SessionVariablePoolResponseDto } from "../sessionVariables/types";
import type { SessionMediaAggregateDto } from "../sessionMedia/types";
import type {
  SessionFileChangesStatus, SessionFileChangesSummaryDto,
} from "../sessionFileChanges/types";

export type TabPreviewTone = "normal" | "muted" | "warning";

export interface TabPreviewRow {
  key: string;
  label: string;
  value: string;
  tone: TabPreviewTone;
}

export interface TabPreviewSection {
  key: string;
  title: string | null;
  rows: readonly TabPreviewRow[];
  notice: string | null;
}

export interface TabPreviewNextEvent {
  taskId: string;
  name: string;
  kind: "cron" | "wait";
  nextAt: number;
  remainingMs: number;
  reminder: string | null;
  due: boolean;
}

export interface TabPreviewModel {
  sections: readonly TabPreviewSection[];
  nextEvent: TabPreviewNextEvent | null;
  footnote: string | null;
}

/** 媒体预览只读状态：聚合独立于当前页，pageState 仅提供加载/过期/错误/归档。 */
export interface TabPreviewMediaStats {
  aggregate: SessionMediaAggregateDto | null;
  loading: boolean;
  error: string | null;
  stale: boolean;
  archived: boolean;
}

/** 变量预览只读状态：pool 为 null 表示尚未读取，loading 区分读取中。 */
export interface TabPreviewVariableStats {
  pool: SessionVariablePoolResponseDto | null;
  loading: boolean;
  error: string | null;
}

/** 文件修改预览只读快照：只消费唯一 Hook 已加载的摘要与页面状态。 */
export interface TabPreviewFileChangesInput {
  summary: SessionFileChangesSummaryDto | null;
  summaryStatus: SessionFileChangesStatus;
  summaryError: string | null;
  pageLoaded: boolean;
  pageStale: boolean;
  pageError: string | null;
}

export interface TabPreviewResourcesInput {
  sessionId: string | null;
  images: number;
  downloads: number;
  loading: boolean;
  error: string | null;
}

export interface TabPreviewCharactersInput {
  profiles: readonly CharacterProfileEntryDto[] | null;
  loading: boolean;
  error: string | null;
}

export interface TabPreviewSandboxInput {
  spaces: readonly DynamicSandboxSpaceWithAvailability[] | null;
  loading: boolean;
  error: string | null;
}

export interface TabPreviewSiteInput {
  status: SiteStatus;
  indexUrl: string;
}

export interface TabPreviewLlmInput {
  profilesCount: number | null;
  profilesStatus: LlmLoadStatus;
  profilesError: string | null;
  profilesWarning: string | null;
  selectionStatus: SessionLlmSelectionStatus;
  selectionError: string | null;
  pendingProfileName: string;
  approvalStatus: LlmLoadStatus;
  metadataStatus: LlmLoadStatus;
  approvalError: string | null;
  metadataError: string | null;
  approvalProfileName: string | null;
  metadataProfileName: string | null;
  approvalAvailable: boolean;
  metadataAvailable: boolean;
}

export interface TabPreviewInput {
  sessionId: string;
  sessionGeneration: number;
  sessionArchived: boolean | null;
  processing: boolean | null;
  resources: TabPreviewResourcesInput | null;
  knownHistoryCount: number;
  shells: SessionResourceSnapshot<ShellInfo[]>;
  cronTasks: SessionResourceSnapshot<CronTask[]>;
  dynamicEndpoints: SessionResourceSnapshot<DynamicEndpoint[]>;
  subagents: Readonly<Record<string, SubagentSession>>;
  characters: TabPreviewCharactersInput;
  sandbox: TabPreviewSandboxInput;
  site: TabPreviewSiteInput;
  llm: TabPreviewLlmInput;
  media: TabPreviewMediaStats;
  variables: TabPreviewVariableStats;
  fileChanges: TabPreviewFileChangesInput;
  now: number;
}

export type TabPreviewSelector = (input: TabPreviewInput) => TabPreviewModel;