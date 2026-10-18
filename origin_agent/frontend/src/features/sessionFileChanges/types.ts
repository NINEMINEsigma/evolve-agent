/**
 * Session file changes DTOs. Wire dates stay validated ISO-8601 strings (never
 * Date objects) and every count is a JavaScript safe integer. Malformed data is
 * a protocol error, never truncated or coerced to zero.
 */
export type SessionFileChangeKind = "file" | "directory";

export type SessionFileChangeDisplayState = "created" | "modified" | "deleted";

export type SessionFileChangeAction = "create" | "modify" | "delete" | "copy" | "move";

export type SessionFileChangeToolName = "Write" | "PatchEdit" | "Delete" | "Copy" | "Move";

export interface SessionFileChangeActorDto {
  session_id: string;
  character_name: string;
}

export interface SessionFileChangeEntryDto {
  path: string;
  kind: SessionFileChangeKind;
  display_state: SessionFileChangeDisplayState;
  created_by_session: boolean;
  operation_count: number;
  last_operation: SessionFileChangeAction;
  last_tool_name: SessionFileChangeToolName;
  actors: SessionFileChangeActorDto[];
  last_operated_at: string;
  last_revision: number;
  source_path: string | null;
  destination_path: string | null;
}

export interface SessionFileChangesSummaryDto {
  session_id: string;
  revision: number;
  file_count: number;
  directory_count: number;
  operation_count: number;
  last_operated_at: string | null;
}

export interface SessionFileChangesPageDto {
  summary: SessionFileChangesSummaryDto;
  offset: number;
  limit: number;
  total_count: number;
  items: SessionFileChangeEntryDto[];
}

/** Shared request status union for the summary and page chains. */
export type SessionFileChangesStatus = "idle" | "loading" | "refreshing" | "ready" | "error";

export interface UseSessionFileChangesState {
  summary: SessionFileChangesSummaryDto | null;
  summaryStatus: SessionFileChangesStatus;
  summaryError: string | null;
  page: SessionFileChangesPageDto | null;
  pageStatus: SessionFileChangesStatus;
  pageError: string | null;
  /** Derived: pageError present or the loaded page revision differs from the latest summary. */
  pageStale: boolean;
  treeEntries: readonly SessionFileChangeEntryDto[] | null;
  treeStatus: SessionFileChangesStatus;
  treeError: string | null;
  treeStale: boolean;
  offset: number;
  setOffset: (offset: number) => void;
  refresh: () => Promise<void>;
}
