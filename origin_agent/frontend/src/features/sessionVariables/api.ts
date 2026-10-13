import { TIMING } from "../../constants/timing";
import { SESSION_VARIABLE_PRESENTATION } from "../../constants/sessionVariables";
import { RequestTimeoutError } from "../../services/fetchWithTimeout";
import type {
  SessionVariableEntryDto, SessionVariableIssueDto, SessionVariableMetadataDto,
  SessionVariablePoolResponseDto,
} from "./types";

export class SessionVariablesRequestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "SessionVariablesRequestError";
  }
}

function record(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Invalid session variable response object");
  }
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[]): void {
  if (Object.keys(value).length !== keys.length || keys.some((key) => !(key in value))) {
    throw new Error("Invalid session variable response fields");
  }
}

function text(value: unknown): string {
  if (typeof value !== "string") throw new Error("Expected a string in session variable response");
  return value;
}

function nullableText(value: unknown): string | null {
  return value === null ? null : text(value);
}

function flag(value: unknown): boolean {
  if (typeof value !== "boolean") throw new Error("Expected a boolean in session variable response");
  return value;
}

function number(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)
    || Math.abs(value) > SESSION_VARIABLE_PRESENTATION.SAFE_NUMBER_MAX) {
    throw new Error("Expected a finite safe number in session variable response");
  }
  return value;
}

function list<T>(value: unknown, decode: (item: unknown) => T): T[] {
  if (!Array.isArray(value)) throw new Error("Expected an array in session variable response");
  return value.map(decode);
}

function issue(payload: unknown): SessionVariableIssueDto {
  const value = record(payload);
  exactKeys(value, ["path", "kind", "code", "message", "key"]);
  const kind = value.kind;
  if (kind !== "value" && kind !== "metadata" && kind !== "constraint" && kind !== "path") {
    throw new Error("Invalid variable issue kind");
  }
  return { path: text(value.path), kind, code: text(value.code), message: text(value.message), key: nullableText(value.key) };
}

function metadata(payload: unknown): SessionVariableMetadataDto {
  const value = record(payload);
  exactKeys(value, ["label", "description", "min", "max", "integer", "percent", "display"]);
  const display = value.display;
  if (display !== "auto" && display !== "number" && display !== "bar" && display !== "gauge") {
    throw new Error("Invalid variable display kind");
  }
  return {
    label: text(value.label), description: text(value.description),
    min: value.min === null ? null : number(value.min),
    max: value.max === null ? null : number(value.max),
    integer: flag(value.integer), percent: flag(value.percent), display,
  };
}

function entry(payload: unknown): SessionVariableEntryDto {
  const value = record(payload);
  exactKeys(value, ["id", "path", "metadata_path", "group", "kind", "value", "raw_value", "raw_metadata", "metadata", "issues"]);
  const kind = value.kind;
  let decodedValue: string | number | null;
  if (kind === "number") decodedValue = number(value.value);
  else if (kind === "string") decodedValue = text(value.value);
  else if (kind === "invalid" && value.value === null) decodedValue = null;
  else throw new Error("Invalid variable kind or value");
  let rawMetadata: Record<string, string> | null = null;
  if (value.raw_metadata !== null) {
    rawMetadata = Object.create(null) as Record<string, string>;
    for (const [key, raw] of Object.entries(record(value.raw_metadata))) rawMetadata[key] = text(raw);
  }
  return {
    id: text(value.id), path: text(value.path), metadata_path: text(value.metadata_path),
    group: text(value.group), kind, value: decodedValue, raw_value: nullableText(value.raw_value),
    raw_metadata: rawMetadata, metadata: metadata(value.metadata), issues: list(value.issues, issue),
  };
}

export function decodeSessionVariablePool(payload: unknown, expectedSessionId: string): SessionVariablePoolResponseDto {
  const value = record(payload);
  exactKeys(value, ["session_id", "directory_path", "root_exists", "scan_complete", "version", "variables", "issues"]);
  const sessionId = text(value.session_id);
  if (sessionId !== expectedSessionId) throw new Error("Session variable response belongs to a different session");
  const variables = list(value.variables, entry);
  const ids = new Set(variables.map((item) => item.id));
  if (ids.size !== variables.length) throw new Error("Duplicate variable identities in response");
  return {
    session_id: sessionId, directory_path: text(value.directory_path),
    root_exists: flag(value.root_exists), scan_complete: flag(value.scan_complete),
    version: text(value.version), variables, issues: list(value.issues, issue),
  };
}

function errorDetail(payload: unknown, status: number): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail: unknown = payload.detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string") {
      const code = "code" in detail && typeof detail.code === "string" ? ` (${detail.code})` : "";
      const path = "path" in detail && typeof detail.path === "string" && detail.path ? ` · ${detail.path}` : "";
      return detail.message + code + path;
    }
  }
  return `HTTP ${status}`;
}

export async function fetchSessionVariables(sessionId: string, signal: AbortSignal): Promise<SessionVariablePoolResponseDto> {
  const started = performance.now();
  const timeoutMs = TIMING.CRITICAL_REQUEST_TIMEOUT;
  const controller = new AbortController();
  const abortError = () => new DOMException("The operation was aborted", "AbortError");
  if (signal.aborted) throw abortError();
  let rejectCutoff: (reason: Error) => void = () => {};
  const cutoff = new Promise<never>((_, reject) => { rejectCutoff = reject; });
  const abort = () => { controller.abort(); rejectCutoff(abortError()); };
  const timeoutError = () => new RequestTimeoutError("session_variables", timeoutMs, performance.now() - started);
  const checkDeadline = () => {
    if (signal.aborted) throw abortError();
    if (performance.now() - started >= timeoutMs) throw timeoutError();
  };
  signal.addEventListener("abort", abort, { once: true });
  let timedOut = false;
  const timer = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
    rejectCutoff(timeoutError());
  }, timeoutMs);
  const request = async () => {
    try {
      const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/variables`, {
        signal: controller.signal, cache: "no-store",
      });
      const body = await response.text();
      checkDeadline();
      let payload: unknown;
      try { payload = JSON.parse(body); }
      catch {
        checkDeadline();
        if (!response.ok) throw new SessionVariablesRequestError(`HTTP ${response.status}`, response.status);
        throw new Error("Invalid JSON in session variable response");
      }
      checkDeadline();
      if (!response.ok) throw new SessionVariablesRequestError(errorDetail(payload, response.status), response.status);
      const result = decodeSessionVariablePool(payload, sessionId);
      checkDeadline();
      return result;
    } catch (error) {
      // 超时触发的 abort 先于截止 Promise 赢得 race 时，还原为超时错误，
      // 与既有 fetchWithTimeout 的 timedOut 判定保持一致。
      if (timedOut) throw timeoutError();
      if (signal.aborted) throw abortError();
      throw error;
    }
  };
  try {
    return await Promise.race([request(), cutoff]);
  } finally {
    window.clearTimeout(timer);
    signal.removeEventListener("abort", abort);
  }
}
