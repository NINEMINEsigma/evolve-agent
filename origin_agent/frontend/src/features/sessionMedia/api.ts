import { SESSION_MEDIA } from "../../constants/sessionMedia";
import { TIMING } from "../../constants/timing";
import { RequestTimeoutError } from "../../services/fetchWithTimeout";
import type {
  SessionMediaItemDto, SessionMediaListResponseDto, SessionMediaUpdateResponseDto,
} from "./types";

export class SessionMediaRequestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "SessionMediaRequestError";
  }
}

function record(payload: unknown, keys: readonly string[]): Record<string, unknown> {
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("Invalid media response object");
  }
  const value = payload as Record<string, unknown>;
  if (Object.keys(value).length !== keys.length || keys.some((key) => !(key in value))) {
    throw new Error("Invalid media response fields");
  }
  return value;
}

function text(value: unknown): string {
  if (typeof value !== "string") throw new Error("Expected a string in media response");
  return value;
}

function nullableText(value: unknown): string | null {
  return value === null ? null : text(value);
}

function integer(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    throw new Error("Expected a nonnegative safe integer in media response");
  }
  return value;
}

function flag(value: unknown): boolean {
  if (typeof value !== "boolean") throw new Error("Expected a boolean in media response");
  return value;
}

function item(payload: unknown): SessionMediaItemDto {
  const value = record(payload, [
    "media_id", "history_index", "block_index", "media_type", "role", "character_name",
    "source_path", "tool_call_id", "send_multimodal", "has_forward_description",
    "mime_type", "inline_payload_chars", "preview_available",
  ]);
  const mediaId = text(value.media_id);
  if (!SESSION_MEDIA.ID_PATTERN.test(mediaId)) throw new Error("Invalid media instance identity");
  const mediaType = value.media_type;
  if (mediaType !== "image" && mediaType !== "audio" && mediaType !== "video") {
    throw new Error("Invalid media type");
  }
  const role = value.role;
  if (role !== "user" && role !== "assistant" && role !== "system" && role !== "tool") {
    throw new Error("Invalid media message role");
  }
  const source = nullableText(value.source_path);
  if (source !== null && Array.from(source).length > SESSION_MEDIA.SOURCE_MAX_CHARS) {
    throw new Error("Media source label exceeds its limit");
  }
  return {
    media_id: mediaId, history_index: integer(value.history_index), block_index: integer(value.block_index),
    media_type: mediaType, role, character_name: nullableText(value.character_name),
    source_path: source, tool_call_id: nullableText(value.tool_call_id),
    send_multimodal: flag(value.send_multimodal), has_forward_description: flag(value.has_forward_description),
    mime_type: nullableText(value.mime_type),
    inline_payload_chars: value.inline_payload_chars === null ? null : integer(value.inline_payload_chars),
    preview_available: flag(value.preview_available),
  };
}

export function decodeSessionMediaList(payload: unknown, expectedSessionId: string): SessionMediaListResponseDto {
  const value = record(payload, ["session_id", "history_count", "total_count", "offset", "limit", "editable", "items"]);
  const sessionId = text(value.session_id);
  if (sessionId !== expectedSessionId) throw new Error("Media response belongs to a different session");
  const offset = integer(value.offset);
  const limit = integer(value.limit);
  const total = integer(value.total_count);
  const historyCount = integer(value.history_count);
  if (limit < 1 || limit > SESSION_MEDIA.MAX_PAGE_SIZE || !Array.isArray(value.items)) {
    throw new Error("Invalid media response page");
  }
  const items = value.items.map(item);
  if (items.length !== Math.min(limit, Math.max(total - offset, 0))
    || new Set(items.map((entry) => entry.media_id)).size !== items.length
    || items.some((entry) => entry.history_index >= historyCount)) {
    throw new Error("Inconsistent media response page");
  }
  return {
    session_id: sessionId, history_count: historyCount, total_count: total,
    offset, limit, editable: flag(value.editable), items,
  };
}

export function decodeSessionMediaUpdate(
  payload: unknown, expectedSessionId: string, expectedMediaId: string,
): SessionMediaUpdateResponseDto {
  const value = record(payload, ["session_id", "item"]);
  const sessionId = text(value.session_id);
  const entry = item(value.item);
  if (sessionId !== expectedSessionId || entry.media_id !== expectedMediaId) {
    throw new Error("Media update response belongs to a different target");
  }
  return { session_id: sessionId, item: entry };
}

function mediaUrl(sessionId: string): string {
  return `${SESSION_MEDIA.API_PREFIX}${encodeURIComponent(sessionId)}${SESSION_MEDIA.API_SUFFIX}`;
}

export function mediaContentUrl(sessionId: string, mediaId: string): string {
  return `${mediaUrl(sessionId)}/${encodeURIComponent(mediaId)}${SESSION_MEDIA.CONTENT_SUFFIX}`;
}

function errorDetail(payload: unknown, status: number): string {
  if (payload !== null && typeof payload === "object" && "detail" in payload && typeof payload.detail === "string") {
    return payload.detail;
  }
  return `HTTP ${status}`;
}

async function request<T>(
  url: string, init: RequestInit, signal: AbortSignal, decode: (payload: unknown) => T,
): Promise<T> {
  const started = performance.now();
  const timeoutMs = TIMING.CRITICAL_REQUEST_TIMEOUT;
  const controller = new AbortController();
  const abortError = () => new DOMException("The operation was aborted", "AbortError");
  if (signal.aborted) throw abortError();
  let rejectCutoff: (reason: Error) => void = () => {};
  const cutoff = new Promise<never>((_, reject) => { rejectCutoff = reject; });
  const timeoutError = () => new RequestTimeoutError("session_media", timeoutMs, performance.now() - started);
  const abort = () => { controller.abort(); rejectCutoff(abortError()); };
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
  const run = async () => {
    try {
      const response = await fetch(url, { ...init, signal: controller.signal, cache: "no-store" });
      const body = await response.text();
      checkDeadline();
      let payload: unknown;
      try { payload = JSON.parse(body); }
      catch {
        checkDeadline();
        if (!response.ok) throw new SessionMediaRequestError(`HTTP ${response.status}`, response.status);
        throw new Error("Invalid JSON in media response");
      }
      checkDeadline();
      if (!response.ok) throw new SessionMediaRequestError(errorDetail(payload, response.status), response.status);
      const result = decode(payload);
      checkDeadline();
      return result;
    } catch (failure) {
      if (timedOut) throw timeoutError();
      if (signal.aborted) throw abortError();
      throw failure;
    }
  };
  try { return await Promise.race([run(), cutoff]); }
  finally {
    window.clearTimeout(timer);
    signal.removeEventListener("abort", abort);
  }
}

export function fetchSessionMedia(
  sessionId: string, offset: number, limit: number, signal: AbortSignal,
): Promise<SessionMediaListResponseDto> {
  return request(`${mediaUrl(sessionId)}?offset=${offset}&limit=${limit}`, {}, signal, (payload) => {
    const result = decodeSessionMediaList(payload, sessionId);
    if (result.offset !== offset || result.limit !== limit) throw new Error("Media response has a different page range");
    return result;
  });
}

export function updateSessionMedia(
  sessionId: string, mediaId: string, sendMultimodal: boolean,
  expectedSendMultimodal: boolean, signal: AbortSignal,
): Promise<SessionMediaUpdateResponseDto> {
  return request(`${mediaUrl(sessionId)}/${encodeURIComponent(mediaId)}`, {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ send_multimodal: sendMultimodal, expected_send_multimodal: expectedSendMultimodal }),
  }, signal, (payload) => {
    const result = decodeSessionMediaUpdate(payload, sessionId, mediaId);
    if (result.item.send_multimodal !== sendMultimodal) throw new Error("Media update did not confirm the requested state");
    return result;
  });
}
