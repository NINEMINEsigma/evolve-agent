import { TIMING } from "../../constants/timing";
import { fetchJsonWithTimeout } from "../../services/fetchJsonWithTimeout";
import { decodeHttpError, type HttpResponseError } from "../../services/httpErrors";
import type { FetchJsonWithTimeoutOptions } from "../../services/fetchJsonWithTimeout";

export interface SessionTabCapabilitiesDto {
  session_id: string;
  media_count: number;
  variables_available: boolean;
}

export class SessionTabCapabilitiesRequestError extends Error {
  constructor(message: string, readonly status: number, readonly httpError?: HttpResponseError) {
    super(message);
    this.name = "SessionTabCapabilitiesRequestError";
  }
}

function record(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Invalid session tab capabilities response object");
  }
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[]): void {
  if (Object.keys(value).length !== keys.length || keys.some((key) => !(key in value))) {
    throw new Error("Invalid session tab capabilities response fields");
  }
}

function text(value: unknown): string {
  if (typeof value !== "string") throw new Error("Expected a session ID in capabilities response");
  return value;
}

function count(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    throw new Error("Expected a nonnegative media count in capabilities response");
  }
  return value;
}

function flag(value: unknown): boolean {
  if (typeof value !== "boolean") throw new Error("Expected a boolean in capabilities response");
  return value;
}

export function decodeSessionTabCapabilities(
  payload: unknown, expectedSessionId: string,
): SessionTabCapabilitiesDto {
  const value = record(payload);
  exactKeys(value, ["session_id", "media_count", "variables_available"]);
  const sessionId = text(value.session_id);
  if (sessionId !== expectedSessionId) {
    throw new Error("Session tab capabilities belong to a different session");
  }
  return {
    session_id: sessionId,
    media_count: count(value.media_count),
    variables_available: flag(value.variables_available),
  };
}

function createHttpError(status: number, payload: unknown | null): Error {
  const error = decodeHttpError(status, payload);
  return new SessionTabCapabilitiesRequestError(error.message, status, error);
}

export function fetchSessionTabCapabilities(
  sessionId: string, signal: AbortSignal,
): Promise<SessionTabCapabilitiesDto> {
  const options: FetchJsonWithTimeoutOptions = {
    timeoutMs: TIMING.CRITICAL_REQUEST_TIMEOUT,
    phase: "session_tab_capabilities",
    createHttpError,
  };
  return fetchJsonWithTimeout(
    `/api/sessions/${encodeURIComponent(sessionId)}/tab-capabilities`,
    { signal, cache: "no-store" },
    options,
    (payload) => decodeSessionTabCapabilities(payload, sessionId),
  );
}
