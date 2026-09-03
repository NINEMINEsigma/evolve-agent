import type {
  AgentspaceEvent,
  FileEntry,
  FileLock,
  FileSnapshot,
  SyncState,
  TrashEntry,
} from "../types";

interface ErrorDetail {
  code?: string;
  message?: string;
  path?: string;
  current_version?: string | null;
  locks?: FileLock[];
}

export class AgentspaceApiError extends Error {
  status: number;
  code: string;
  detail: ErrorDetail;

  constructor(status: number, detail: ErrorDetail) {
    super(detail.message || `Agentspace 请求失败（HTTP ${status}）`);
    this.name = "AgentspaceApiError";
    this.status = status;
    this.code = detail.code || "http_error";
    this.detail = detail;
  }
}

function operationId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function createOperationId(): string {
  return operationId();
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const rawDetail = (payload as { detail?: unknown } | null)?.detail;
    const detail: ErrorDetail =
      typeof rawDetail === "string"
        ? { message: rawDetail }
        : rawDetail && typeof rawDetail === "object"
          ? (rawDetail as ErrorDetail)
          : { message: `Agentspace 请求失败（HTTP ${response.status}）` };
    throw new AgentspaceApiError(response.status, detail);
  }
  return payload as T;
}

function jsonInit(method: string, body: object): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}
export function normalizeEditorText(content: string): string {
  // Monaco 使用 LF 作为内部换行符；统一显示格式，避免 CRLF 被误报为逐行差异。
  return content.replace(/\r\n?/g, "\n");
}

export async function getTextVersion(content: string): Promise<string> {
  const bytes = new TextEncoder().encode(normalizeEditorText(content));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
}

function normalizeSnapshot(snapshot: FileSnapshot): FileSnapshot {
  return { ...snapshot, content: normalizeEditorText(snapshot.content) };
}

export async function listDirectory(path: string): Promise<FileEntry[]> {
  const result = await requestJson<{ entries: FileEntry[] }>(
    `/api/agentspace/list?path=${encodeURIComponent(path)}`,
  );
  return result.entries;
}

export async function readFile(path: string): Promise<FileSnapshot> {
  const snapshot = await requestJson<FileSnapshot>(
    `/api/agentspace/read?path=${encodeURIComponent(path)}`,
  );
  return normalizeSnapshot(snapshot);
}

export async function writeFile(
  path: string,
  content: string,
  expectedVersion: string | null,
  requestOperationId = operationId(),
): Promise<FileSnapshot> {
  const snapshot = await requestJson<FileSnapshot>(
    "/api/agentspace/write",
    jsonInit("POST", {
      path,
      content,
      expected_version: expectedVersion,
      operation_id: requestOperationId,
    }),
  );
  return normalizeSnapshot(snapshot);
}

export async function createDirectory(path: string): Promise<FileEntry> {
  const result = await requestJson<{ entry: FileEntry }>(
    "/api/agentspace/mkdir",
    jsonInit("POST", { path, operation_id: operationId() }),
  );
  return result.entry;
}

export function renamePath(
  path: string,
  newName: string,
): Promise<{ old_path: string; new_path: string; operation_id: string }> {
  return requestJson(
    "/api/agentspace/rename",
    jsonInit("POST", {
      path,
      new_name: newName,
      operation_id: operationId(),
    }),
  );
}

export async function moveToTrash(path: string): Promise<TrashEntry> {
  const result = await requestJson<{ entry: TrashEntry }>(
    "/api/agentspace/delete",
    jsonInit("POST", { path, operation_id: operationId() }),
  );
  return result.entry;
}

export async function listTrash(): Promise<TrashEntry[]> {
  const result = await requestJson<{ entries: TrashEntry[] }>(
    "/api/agentspace/trash",
  );
  return result.entries;
}

export function restoreTrash(
  entryId: string,
): Promise<{ entry: TrashEntry; restored_path: string; operation_id: string }> {
  return requestJson(
    `/api/agentspace/trash/${encodeURIComponent(entryId)}/restore`,
    jsonInit("POST", { operation_id: operationId() }),
  );
}

export function purgeTrash(entryId: string): Promise<void> {
  return requestJson<void>(
    `/api/agentspace/trash/${encodeURIComponent(entryId)}`,
    jsonInit("DELETE", { operation_id: operationId() }),
  );
}

export function emptyTrash(): Promise<{ deleted: number; failures: string[] }> {
  return requestJson(
    "/api/agentspace/trash",
    jsonInit("DELETE", { operation_id: operationId() }),
  );
}

export async function getLocks(): Promise<FileLock[]> {
  const result = await requestJson<{ locks: FileLock[] }>(
    "/api/agentspace/locks",
  );
  return result.locks;
}

export function connectAgentspaceEvents(
  onEvent: (event: AgentspaceEvent) => void,
  onState: (state: SyncState) => void,
): () => void {
  onState("connecting");
  const source = new EventSource("/api/agentspace/events");
  source.onopen = () => onState("live");
  source.onerror = () => onState("degraded");
  const listener = (raw: Event) => {
    try {
      const message = raw as MessageEvent<string>;
      onEvent(JSON.parse(message.data) as AgentspaceEvent);
    } catch {
      onState("degraded");
    }
  };
  source.addEventListener("agentspace", listener);
  return () => {
    source.removeEventListener("agentspace", listener);
    source.close();
  };
}
