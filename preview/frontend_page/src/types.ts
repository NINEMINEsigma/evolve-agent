import type {
  ApprovalMode, AskRequest, ConfirmRequest, CronTask, DynamicEndpoint, LlmProfile,
  MainSessionActivitySnapshot, MessageContent, SessionInfo, ShellInfo, SubagentSession,
  TaskProgress, WSMessage, DynamicSandboxSpaceWithAvailability,
} from "@origin/types";
import type { HistoryContentRowDto } from "@origin/features/chat/types";
import type { SessionMediaItemDto } from "@origin/features/sessionMedia/types";
import type { SessionFileChangeEntryDto } from "@origin/features/sessionFileChanges/types";
import type { SessionVariablePoolResponseDto } from "@origin/features/sessionVariables/types";
import type { TabId } from "@origin/features/tabs/registry";
import type { PreviewStore } from "./runtime/store";
import type { PreviewEvents } from "./runtime/events";

export type PreviewSceneId = "showcase" | "empty" | "multi" | "approval" | "question" | "archived" | "visual" | "onboarding";
export interface PreviewOptions {
  scene: PreviewSceneId;
  tab: TabId;
  sessionId: string;
  controls: boolean;
  editor: boolean;
}
export interface PreviewScene { id: PreviewSceneId; label: string; sessionId: string }
export interface PreviewSession {
  info: SessionInfo;
  rows: HistoryContentRowDto[];
  historyCount: number;
  profileName: string;
  approvalMode: ApprovalMode;
  agents: string[];
  activity: MainSessionActivitySnapshot | null;
  tokenUsage: number;
  contextTokens: number;
  media: SessionMediaItemDto[];
  changes: SessionFileChangeEntryDto[];
  revision: number;
  variables: SessionVariablePoolResponseDto;
  shells: ShellInfo[];
  cronTasks: CronTask[];
  subagents: Record<string, SubagentSession>;
  taskProgress: Record<string, TaskProgress>;
  endpoints: DynamicEndpoint[];
  confirm: ConfirmRequest | null;
  ask: AskRequest | null;
}
export interface PreviewCatalog {
  profiles: LlmProfile[];
  spaces: DynamicSandboxSpaceWithAvailability[];
}
export interface PreviewUserInput {
  content: MessageContent;
  clientMessageId?: string;
  profileName?: string;
  characterName?: string;
  targetSessions?: string[];
  requireToolCall?: boolean;
  regenerate?: boolean;
}
export interface PreviewFile { path: string; kind: "file" | "dir"; content: string }
export interface PreviewFault { code: string; message: string; path?: string }
export interface PreviewRuntime {
  options: PreviewOptions;
  store: PreviewStore;
  events: PreviewEvents;
  pendingRequests: number;
  disposed: boolean;
  paused: boolean;
  blobs: Set<string>;
}
export interface PreviewController {
  readonly ready: Promise<void>;
  readonly scene: PreviewSceneId;
  readonly state: "preparing" | "ready" | "failed";
  readonly pendingRequests: number;
  reset: () => void;
  freeze: () => void;
  resume: () => void;
}
export interface PreviewSocketSink {
  sessionId: string;
  emit: (message: WSMessage) => void;
  terminate: (code: number) => void;
}
