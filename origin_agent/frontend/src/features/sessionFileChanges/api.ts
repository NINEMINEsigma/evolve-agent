/**
 * Typed, read-only REST access for session file changes. Responses are decoded
 * strictly: every DTO field, enum, count, page boundary and transfer endpoint is
 * validated, and malformed data raises a protocol error instead of being
 * filtered or coerced. Requests reuse the cancellable 15s JSON helper.
 */
import { TIMING } from "../../constants/timing";
import { fetchJsonWithTimeout } from "../../services/fetchJsonWithTimeout";
import type {
  SessionFileChangeAction, SessionFileChangeActorDto, SessionFileChangeDisplayState, SessionFileChangeEntryDto,
  SessionFileChangeKind, SessionFileChangeToolName, SessionFileChangesPageDto,
  SessionFileChangesSummaryDto,
} from "./types";

export class SessionFileChangesRequestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "SessionFileChangesRequestError";
  }
}

export class SessionFileChangesProtocolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SessionFileChangesProtocolError";
  }
}

const UTC_TIMESTAMP_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}\+00:00$/;

const OPERATIONS: readonly SessionFileChangeAction[] = ["create", "modify", "delete", "copy", "move"];
const KINDS: readonly SessionFileChangeKind[] = ["file", "directory"];
const TOOL_NAMES: readonly SessionFileChangeToolName[] = ["Write", "PatchEdit", "Delete", "Copy", "Move"];
const DISPLAY_STATES: readonly SessionFileChangeDisplayState[] = ["created", "modified", "deleted"];
const TOOL_OPERATIONS: Record<SessionFileChangeToolName, readonly SessionFileChangeAction[]> = {
  Write: ["create", "modify"],
  PatchEdit: ["modify"],
  Delete: ["delete"],
  Copy: ["copy"],
  Move: ["move"],
};

function invalid(message: string): never {
  throw new SessionFileChangesProtocolError(message);
}

function record(payload: unknown, keys: readonly string[]): Record<string, unknown> {
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
    invalid("Invalid file changes response object");
  }
  const value = payload as Record<string, unknown>;
  if (Object.keys(value).length !== keys.length || keys.some((key) => !(key in value))) {
    invalid("Invalid file changes response fields");
  }
  return value;
}

function nonEmptyText(value: unknown): string {
  if (typeof value !== "string" || !value) invalid("Expected non-empty text in file changes response");
  return value;
}

function integer(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    invalid("Expected a nonnegative safe integer in file changes response");
  }
  return value;
}

function positiveInteger(value: unknown): number {
  const parsed = integer(value);
  if (parsed < 1) invalid("Expected a positive safe integer in file changes response");
  return parsed;
}

function action(value: unknown): SessionFileChangeAction {
  if (typeof value !== "string" || !OPERATIONS.includes(value as SessionFileChangeAction)) {
    invalid("Invalid file change operation");
  }
  return value as SessionFileChangeAction;
}

function kind(value: unknown): SessionFileChangeKind {
  if (typeof value !== "string" || !KINDS.includes(value as SessionFileChangeKind)) {
    invalid("Invalid file change target kind");
  }
  return value as SessionFileChangeKind;
}

function displayState(value: unknown): SessionFileChangeDisplayState {
  if (typeof value !== "string" || !DISPLAY_STATES.includes(value as SessionFileChangeDisplayState)) {
    invalid("Invalid file change display state");
  }
  return value as SessionFileChangeDisplayState;
}

function boolean(value: unknown): boolean {
  if (typeof value !== "boolean") invalid("Expected a boolean in file changes response");
  return value;
}

function toolName(value: unknown): SessionFileChangeToolName {
  if (typeof value !== "string" || !TOOL_NAMES.includes(value as SessionFileChangeToolName)) {
    invalid("Invalid file change tool name");
  }
  return value as SessionFileChangeToolName;
}

/** Canonical UTC ISO-8601 with fixed millisecond precision and a +00:00 offset. */
function timestamp(value: unknown): string {
  if (typeof value !== "string" || !UTC_TIMESTAMP_PATTERN.test(value)) {
    invalid("Invalid file change UTC timestamp");
  }
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) invalid("Invalid file change UTC timestamp");
  if (new Date(parsed).toISOString().replace("Z", "+00:00") !== value) {
    invalid("Non-canonical file change UTC timestamp");
  }
  return value;
}

/** Canonical logical path: namespace, optional relative part without empty or dot segments. */
function logicalPath(value: unknown): string {
  const path = nonEmptyText(value);
  const separator = path.indexOf(":");
  if (separator <= 0) invalid("File change path requires a namespace");
  const namespace = path.slice(0, separator);
  if (namespace !== namespace.trim() || /[/\\\x00\r\n]/.test(namespace)) {
    invalid("Invalid file change namespace");
  }
  const relative = path.slice(separator + 1);
  if (relative === "") return path;
  if (relative.startsWith("/") || relative.endsWith("/") || relative.includes("\\") || relative.includes("\x00")) {
    invalid("Invalid file change relative path");
  }
  for (const segment of relative.split("/")) {
    if (segment === "" || segment === "." || segment === ".." || segment.includes(":")) {
      invalid("Non-canonical file change relative path");
    }
  }
  return path;
}

function actor(payload: unknown): SessionFileChangeActorDto {
  const value = record(payload, ["session_id", "character_name"]);
  return {
    session_id: nonEmptyText(value.session_id),
    character_name: nonEmptyText(value.character_name),
  };
}

function entry(payload: unknown, summaryRevision: number): SessionFileChangeEntryDto {
  const value = record(payload, [
    "path", "kind", "display_state", "created_by_session", "operation_count", "last_operation", "last_tool_name", "actors",
    "last_operated_at", "last_revision", "source_path", "destination_path",
  ]);
  const path = logicalPath(value.path);
  const targetKind = kind(value.kind);
  const state = displayState(value.display_state);
  const createdBySession = boolean(value.created_by_session);
  const operationCount = positiveInteger(value.operation_count);
  const lastOperation = action(value.last_operation);
  const lastToolName = toolName(value.last_tool_name);
  const lastRevision = positiveInteger(value.last_revision);
  if (lastRevision > summaryRevision || operationCount > summaryRevision) {
    invalid("File change entry revision exceeds the summary revision");
  }
  if (!TOOL_OPERATIONS[lastToolName].includes(lastOperation)) {
    invalid("File change tool does not match its operation");
  }
  if (!Array.isArray(value.actors)) invalid("Invalid file change authors");
  const actors = value.actors.map(actor);
  if (actors.length < 1 || actors.length > operationCount) {
    invalid("Invalid file change author count");
  }
  const identities = new Set(actors.map((item) => `${item.session_id}\u0000${item.character_name}`));
  if (identities.size !== actors.length) invalid("Duplicate file change author");
  const lastOperatedAt = timestamp(value.last_operated_at);
  const sourcePath = value.source_path === null ? null : logicalPath(value.source_path);
  const destinationPath = value.destination_path === null ? null : logicalPath(value.destination_path);
  if (lastOperation === "copy") {
    if (sourcePath === null || destinationPath === null || path !== destinationPath) {
      invalid("Copy entry requires both endpoints and the destination path");
    }
  } else if (lastOperation === "move") {
    if (sourcePath === null || destinationPath === null
      || (path !== sourcePath && path !== destinationPath)) {
      invalid("Move entry requires both endpoints and one of them as its path");
    }
  } else if (sourcePath !== null || destinationPath !== null) {
    invalid("Non-transfer entry retains transfer endpoints");
  }
  return {
    path,
    kind: targetKind,
    display_state: state,
    created_by_session: createdBySession,
    operation_count: operationCount,
    last_operation: lastOperation,
    last_tool_name: lastToolName,
    actors,
    last_operated_at: lastOperatedAt,
    last_revision: lastRevision,
    source_path: sourcePath,
    destination_path: destinationPath,
  };
}

export function decodeSessionFileChangesSummary(
  payload: unknown, expectedSessionId: string,
): SessionFileChangesSummaryDto {
  const value = record(payload, [
    "session_id", "revision", "file_count", "directory_count", "operation_count", "last_operated_at",
  ]);
  const sessionId = nonEmptyText(value.session_id);
  if (sessionId !== expectedSessionId) invalid("File changes summary belongs to a different session");
  const revision = integer(value.revision);
  const fileCount = integer(value.file_count);
  const directoryCount = integer(value.directory_count);
  const operationCount = integer(value.operation_count);
  if (operationCount !== revision) invalid("File changes operation count must equal the revision");
  const totalCount = fileCount + directoryCount;
  // One successful target adds one revision and touches at most two path rows
  // (a move updates its source and destination), so the entry count is bounded
  // by twice the revision; it is never a per-row sum of operation counts.
  if (!Number.isSafeInteger(totalCount) || totalCount > revision * 2) {
    invalid("File change entry count exceeds the revision bound");
  }
  if ((revision === 0) !== (totalCount === 0)) {
    invalid("Empty file changes summary has an inconsistent revision");
  }
  const lastOperatedAt = value.last_operated_at === null ? null : timestamp(value.last_operated_at);
  if ((totalCount === 0) !== (lastOperatedAt === null)) {
    invalid("File changes summary timestamp does not match its entries");
  }
  return {
    session_id: sessionId,
    revision,
    file_count: fileCount,
    directory_count: directoryCount,
    operation_count: operationCount,
    last_operated_at: lastOperatedAt,
  };
}

export function decodeSessionFileChangesPage(
  payload: unknown, expectedSessionId: string, expectedOffset: number, expectedLimit: number,
): SessionFileChangesPageDto {
  const value = record(payload, ["summary", "offset", "limit", "total_count", "items"]);
  const summary = decodeSessionFileChangesSummary(value.summary, expectedSessionId);
  const offset = integer(value.offset);
  const limit = positiveInteger(value.limit);
  if (offset !== expectedOffset || limit !== expectedLimit) {
    invalid("File changes page has a different range");
  }
  const totalCount = integer(value.total_count);
  if (totalCount !== summary.file_count + summary.directory_count) {
    invalid("File changes page total does not match its summary");
  }
  if (!Array.isArray(value.items)) invalid("Invalid file changes page items");
  const expectedItems = Math.min(limit, Math.max(totalCount - offset, 0));
  if (value.items.length !== expectedItems) invalid("Inconsistent file changes page length");
  const items = value.items.map((item) => entry(item, summary.revision));
  if (new Set(items.map((item) => item.path)).size !== items.length) {
    invalid("Duplicate file change entry path");
  }
  for (let index = 1; index < items.length; index += 1) {
    if (items[index].last_revision > items[index - 1].last_revision) {
      invalid("File change entries are not ordered by revision");
    }
  }
  return { summary, offset, limit, total_count: totalCount, items };
}

function summaryUrl(sessionId: string): string {
  return `/api/sessions/${encodeURIComponent(sessionId)}/file-changes/summary`;
}

function pageUrl(sessionId: string): string {
  return `/api/sessions/${encodeURIComponent(sessionId)}/file-changes`;
}

function errorDetail(payload: unknown, status: number): string {
  if (payload !== null && typeof payload === "object" && "detail" in payload
    && typeof (payload as { detail: unknown }).detail === "string") {
    return (payload as { detail: string }).detail;
  }
  return `HTTP ${status}`;
}

function createHttpError(status: number, payload: unknown): Error {
  return new SessionFileChangesRequestError(errorDetail(payload, status), status);
}

export function fetchSessionFileChangesSummary(
  sessionId: string, signal: AbortSignal,
): Promise<SessionFileChangesSummaryDto> {
  return fetchJsonWithTimeout(
    summaryUrl(sessionId),
    { signal },
    { timeoutMs: TIMING.CRITICAL_REQUEST_TIMEOUT, phase: "session-file-changes-summary", createHttpError },
    (payload) => decodeSessionFileChangesSummary(payload, sessionId),
  );
}

export function fetchSessionFileChangesPage(
  sessionId: string, offset: number, limit: number, signal: AbortSignal,
): Promise<SessionFileChangesPageDto> {
  return fetchJsonWithTimeout(
    `${pageUrl(sessionId)}?offset=${offset}&limit=${limit}`,
    { signal },
    { timeoutMs: TIMING.CRITICAL_REQUEST_TIMEOUT, phase: "session-file-changes-page", createHttpError },
    (payload) => decodeSessionFileChangesPage(payload, sessionId, offset, limit),
  );
}
