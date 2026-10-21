import type { HistoryContentRowDto } from "../chat/types";
import type {
  ExportResourceProof, ExportResourceReadResult, ExportResourceSource, ExportVerifyRequest,
  SessionExportSnapshotDto, SessionExportStamp,
} from "./types";
import { EXPORT_LIMITS } from "./limits";
import { exportLabels } from "./labels";
import { sha256Hex } from "../../utils/sha256";

export class SessionExportRequestError extends Error {
  constructor(readonly code: string, message: string, readonly status: number) { super(message); }
}
export function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid export object");
  return value as Record<string, unknown>;
}
function integer(value: unknown): asserts value is number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) throw new Error("Invalid export integer");
}
function string(value: unknown): asserts value is string {
  if (typeof value !== "string") throw new Error("Invalid export string");
}
function nullableString(value: unknown): void { if (value != null) string(value); }
function strings(value: unknown): void {
  if (!Array.isArray(value) || !value.every((item: unknown) => typeof item === "string")) throw new Error("Invalid export strings");
}
function digest(value: unknown): void {
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) throw new Error("Invalid export digest");
}
function content(value: unknown): void {
  if (typeof value === "string") return;
  if (!Array.isArray(value)) throw new Error("Invalid export content");
  for (const raw of value) {
    const block = record(raw);
    switch (block.type) {
      case "text": string(block.text); break;
      case "image_url": string(record(block.image_url).url); break;
      case "video_url": string(record(block.video_url).url); break;
      case "input_audio": {
        const audio = record(block.input_audio); string(audio.data); string(audio.format); break;
      }
      default: throw new Error("Unknown export media block");
    }
  }
}
function metrics(value: unknown): void {
  if (value == null) return;
  const data = record(value);
  for (const key of ["reasoning_duration_ms", "content_duration_ms", "completion_tokens", "tokens_per_second"]) {
    if (typeof data[key] !== "number" || !Number.isFinite(data[key])) throw new Error("Invalid export metrics");
  }
}
function embedded(value: unknown): void {
  if (value == null) return;
  if (!Array.isArray(value)) throw new Error("Invalid embedded export messages");
  for (const raw of value) {
    const message = record(raw);
    if (message.role !== "user") throw new Error("Invalid embedded message role");
    content(message.content);
    nullableString(message.character_name); nullableString(message.source); nullableString(message.timestamp);
  }
}
function assertRow(value: unknown): asserts value is HistoryContentRowDto {
  const row = record(value);
  string(row.row_id); integer(row.history_index); string(row.role);
  if (!["user", "assistant", "system", "tool", "error"].includes(row.role)) throw new Error("Invalid export role");
  if (row.row_kind !== "message" && row.row_kind !== "tool_card") throw new Error("Invalid export row kind");
  if (typeof row.is_system_status !== "boolean") throw new Error("Invalid status row");
  content(row.content);
  for (const key of ["character_name", "message_suffix", "dynamic_message_suffix", "reasoning_content", "tool_name", "tool_args_raw"]) nullableString(row[key]);
  if (row.visible_characters != null) strings(row.visible_characters);
  if (row.response_characters != null) strings(row.response_characters);
  if (row.requires_response != null && typeof row.requires_response !== "boolean") throw new Error("Invalid response flag");
  if (row.tool_args != null) record(row.tool_args);
  metrics(row.metrics);
  if (row.tool_card != null) {
    const card = record(row.tool_card);
    string(card.tool_call_id); string(card.tool_name); record(card.request_args);
    nullableString(card.request_args_raw);
    if (!["succeeded", "failed", "missing_result"].includes(String(card.status))) throw new Error("Invalid export tool state");
    if (typeof card.is_error !== "boolean") throw new Error("Invalid tool error flag");
    if (card.result_content != null) content(card.result_content);
    if (card.result_history_index != null) integer(card.result_history_index);
    embedded(card.embedded_messages);
    if (card.tool_call_meta != null) record(card.tool_call_meta);
  } else if (row.row_kind === "tool_card") throw new Error("Missing tool card");
}
export function decodeExportSnapshot(value: unknown, expectedSessionId?: string): SessionExportSnapshotDto {
  const data = record(value);
  if (data.format_version !== 1) throw new Error("Unsupported export format");
  string(data.session_id); string(data.captured_at); string(data.title); strings(data.tags);
  if (expectedSessionId && data.session_id !== expectedSessionId) throw new Error("Export session mismatch");
  integer(data.history_count);
  const stamp = record(data.stamp);
  if (typeof stamp.loop_instance_id !== "string" || !/^[0-9a-f]{32}$/.test(stamp.loop_instance_id)) throw new Error("Invalid loop identity");
  integer(stamp.export_epoch);
  digest(stamp.history_digest); digest(stamp.metadata_digest); digest(stamp.visual_digest);
  const limits = record(data.limits);
  for (const key of ["max_history_bytes", "max_snapshot_bytes", "max_messages", "max_rows", "max_nodes", "max_structure_depth", "max_resource_bytes", "max_resource_total_bytes", "max_resources", "max_depth", "max_verify_body_bytes", "max_archive_input_bytes", "request_timeout_seconds", "total_timeout_seconds"]) {
    integer(limits[key]); if (limits[key] === 0) throw new Error("Empty export budget");
  }
  if (!Array.isArray(data.rows) || data.rows.length > (limits.max_rows as number) || data.rows.length > 40_000 || data.history_count > 20_000) throw new Error("Export row budget exceeded");
  const seen = new Set<string>();
  for (const row of data.rows) {
    assertRow(row);
    if (row.history_index >= data.history_count || seen.has(row.row_id)) throw new Error("Invalid export row identity");
    seen.add(row.row_id);
  }
  if (!Array.isArray(data.visuals) || data.visuals.length !== 2) throw new Error("Invalid export visuals");
  const kinds = new Set<string>();
  for (const raw of data.visuals) {
    const visual = record(raw);
    if (visual.kind !== "stage" && visual.kind !== "chat_style") throw new Error("Invalid visual kind");
    if (kinds.has(visual.kind)) throw new Error("Duplicate visual kind");
    kinds.add(visual.kind);
    if (!["ready", "missing", "error"].includes(String(visual.status)) || typeof visual.configured !== "boolean") throw new Error("Invalid visual state");
    if (!["unconfigured", "ready", "missing_entry", "invalid_metadata", "unreadable"].includes(String(visual.availability))) throw new Error("Invalid visual availability");
    string(visual.source_path); string(visual.effective_path); nullableString(visual.entry_path); nullableString(visual.error_code);
  }
  return data as unknown as SessionExportSnapshotDto;
}

export async function fetchExportResponse(
  url: string, init: RequestInit, signal: AbortSignal, maxBytes: number,
): Promise<{ response: Response; bytes: Uint8Array }> {
  const controller = new AbortController();
  const abort = () => controller.abort(signal.reason);
  signal.addEventListener("abort", abort, { once: true });
  if (signal.aborted) abort();
  const timer = window.setTimeout(() => controller.abort(new Error("Export request timed out")), EXPORT_LIMITS.requestMs);
  try {
    const response = await fetch(url, { ...init, signal: controller.signal, cache: "no-store", redirect: "error", credentials: "same-origin" });
    const declared = response.headers.get("Content-Length");
    if (declared && Number(declared) > maxBytes) throw new Error("Export response exceeds byte limit");
    if (!response.body) throw new Error("Missing export response body");
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = [];
    let total = 0;
    try {
      while (true) {
        const item = await reader.read();
        if (item.done) break;
        total += item.value.byteLength;
        if (total > maxBytes) throw new Error("Export response exceeds byte limit");
        chunks.push(item.value);
      }
    } finally { await reader.cancel(); reader.releaseLock(); }
    if (controller.signal.aborted) throw controller.signal.reason;
    const bytes = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    return { response, bytes };
  } finally { window.clearTimeout(timer); signal.removeEventListener("abort", abort); controller.abort(); }
}
function parse(bytes: Uint8Array): unknown { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); }
function fail(response: Response, payload: unknown): never {
  if (response.status === 405) throw new SessionExportRequestError("export_backend_unavailable", exportLabels.backendUnavailable, 405);
  const body = record(payload);
  const detail = typeof body.detail === "object" && body.detail ? record(body.detail) : body;
  throw new SessionExportRequestError(
    typeof detail.code === "string" ? detail.code : "export_failed",
    typeof detail.message === "string" ? detail.message : `HTTP ${response.status}`,
    response.status,
  );
}
function endpoint(sessionId: string, suffix: string): string { return `/api/sessions/${encodeURIComponent(sessionId)}/export/${suffix}`; }
export async function captureSessionExport(sessionId: string, signal: AbortSignal): Promise<SessionExportSnapshotDto> {
  const started = performance.now();
  const { response, bytes } = await fetchExportResponse(endpoint(sessionId, "snapshot"), { method: "POST" }, signal, EXPORT_LIMITS.snapshotBytes);
  const data = parse(bytes);
  if (!response.ok) fail(response, data);
  const snapshot = decodeExportSnapshot(data, sessionId);
  if (signal.aborted) throw signal.reason;
  if (performance.now() - started > EXPORT_LIMITS.requestMs) throw new Error("Export snapshot decoding timed out");
  return snapshot;
}
export async function readSessionExportResource(
  sessionId: string, stamp: SessionExportStamp, source: ExportResourceSource, signal: AbortSignal,
): Promise<ExportResourceReadResult> {
  const { response, bytes } = await fetchExportResponse(endpoint(sessionId, "resource"), {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ stamp, source }),
  }, signal, EXPORT_LIMITS.resourceBytes);
  if (!response.ok) {
    const data = parse(bytes);
    const detail = record(record(data).detail);
    if (detail.proof && ["resource_missing", "resource_denied", "resource_too_large"].includes(String(detail.code))) {
      const proof = record(detail.proof);
      const origin = record(proof.source);
      if (origin.kind !== source.kind || origin.path !== source.path || !["missing", "denied", "too_large"].includes(String(proof.status))) throw new Error("Invalid unavailable proof");
      return { status: "unavailable", code: String(detail.code), proof: proof as unknown as ExportResourceProof };
    }
    fail(response, data);
  }
  const hash = response.headers.get("X-Export-Digest");
  const identity = response.headers.get("X-Export-Identity");
  digest(hash); digest(identity);
  const declaredLength = response.headers.get("Content-Length");
  if (declaredLength === null || !/^\d+$/.test(declaredLength) || Number(declaredLength) !== bytes.byteLength || await sha256Hex(bytes) !== hash) throw new Error("Export resource integrity mismatch");
  if (signal.aborted) throw signal.reason;
  return { status: "saved", bytes, mime: response.headers.get("Content-Type") || "application/octet-stream", proof: {
    source, status: "saved", digest: hash, identity, size: bytes.byteLength,
  } };
}
export async function verifySessionExport(sessionId: string, request: ExportVerifyRequest, signal: AbortSignal): Promise<void> {
  const body = JSON.stringify(request);
  if (new TextEncoder().encode(body).byteLength > EXPORT_LIMITS.verifyBytes) throw new Error("Export proof budget exceeded");
  const { response, bytes } = await fetchExportResponse(endpoint(sessionId, "verify"), { method: "POST", headers: { "Content-Type": "application/json" }, body }, signal, EXPORT_LIMITS.verifyBytes);
  const data = parse(bytes);
  if (!response.ok) fail(response, data);
  const result = record(data);
  if (result.verified !== true || result.session_id !== sessionId || typeof result.verified_at !== "string") throw new Error("Invalid verification response");
}
