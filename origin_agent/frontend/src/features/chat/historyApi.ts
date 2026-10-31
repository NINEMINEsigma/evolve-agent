import type {
  HistoryPageResponseDto,
  HistoryResourcesResponseDto,
  HistorySkeletonResponseDto,
} from "./types";
import { chatTelemetry } from "./chatTelemetry";
import type { ClientDiagnosticPhase } from "../../types";
import { TIMING } from "../../constants/timing";
import { RequestTimeoutError } from "../../services/fetchWithTimeout";
import { fetchJsonWithTimeout } from "../../services/fetchJsonWithTimeout";
import { decodeHttpError, type HttpResponseError } from "../../services/httpErrors";

export class ChatHistoryRequestError extends Error {
  readonly status: number;
  readonly retryable: boolean;

  constructor(message: string, status: number, retryable: boolean, readonly httpError?: HttpResponseError) {
    super(message);
    this.name = "ChatHistoryRequestError";
    this.status = status;
    this.retryable = retryable;
  }
}

function responseObject(value: unknown, sessionId: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid history JSON response");
  const data = value as Record<string, unknown>;
  if (data.session_id !== sessionId || !Number.isSafeInteger(data.history_count) || (data.history_count as number) < 0) throw new Error("Invalid history response identity or count");
  return data;
}
function responseRows(data: Record<string, unknown>): void {
  if (!Array.isArray(data.rows)) throw new Error("Invalid history rows");
  const ids = new Set<string>();
  for (const raw of data.rows) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("Invalid history row");
    const row = raw as Record<string, unknown>;
    if (typeof row.row_id !== "string" || ids.has(row.row_id) || !Number.isSafeInteger(row.history_index)
      || (row.history_index as number) < 0 || (row.history_index as number) >= (data.history_count as number)
      || (row.row_kind !== "message" && row.row_kind !== "tool_card") || typeof row.role !== "string"
      || typeof row.is_system_status !== "boolean") throw new Error("Invalid history row identity");
    ids.add(row.row_id);
  }
}

async function requestJson<T>(
  url: string,
  signal: AbortSignal,
  phase: ClientDiagnosticPhase | undefined,
  decode: (value: unknown) => T,
): Promise<T> {
  const started = performance.now();
  chatTelemetry.record({
    time: Date.now(),
    kind: "history_request",
  });
  try {
    const data = await fetchJsonWithTimeout(url, { signal }, {
      timeoutMs: TIMING.CRITICAL_REQUEST_TIMEOUT,
      phase: phase ?? "history_resources",
      createHttpError: (status, payload) => {
        chatTelemetry.record({ time: Date.now(), kind: "history_response", durationMs: performance.now() - started, status });
        const error = decodeHttpError(status, payload);
        return new ChatHistoryRequestError(error.message, status, status >= 500 || status === 408 || status === 429, error);
      },
    }, decode);
    chatTelemetry.record({ time: Date.now(), kind: "history_response", durationMs: performance.now() - started, status: 200 });
    return data;
  } catch (error) {
    if (error instanceof RequestTimeoutError) {
      chatTelemetry.record({
        time: Date.now(),
        kind: "history_timeout",
        durationMs: error.elapsedMs,
        phase,
      });
    } else if (error instanceof DOMException && error.name === "AbortError") {
      chatTelemetry.record({ time: Date.now(), kind: "history_cancel" });
    }
    throw error;
  }
}

export function fetchHistorySkeleton(
  sessionId: string,
  startIndex: number,
  signal: AbortSignal,
): Promise<HistorySkeletonResponseDto> {
  return requestJson(
    `/api/sessions/${encodeURIComponent(sessionId)}/history/skeleton?start_index=${startIndex}`,
    signal,
    "history_skeleton",
    (value) => {
      const data = responseObject(value, sessionId);
      responseRows(data);
      if (data.start_index !== startIndex || !Number.isSafeInteger(data.row_count) || (data.row_count as number) < 0) throw new Error("Invalid history skeleton range");
      return data as unknown as HistorySkeletonResponseDto;
    },
  );
}

export function fetchHistoryPage(
  sessionId: string,
  startIndex: number,
  limit: number,
  signal: AbortSignal,
): Promise<HistoryPageResponseDto> {
  return requestJson(
    `/api/sessions/${encodeURIComponent(sessionId)}/history/page?start_index=${startIndex}&limit=${limit}`,
    signal,
    "history_page",
    (value) => {
      const data = responseObject(value, sessionId);
      responseRows(data);
      if (data.start_index !== startIndex || !Number.isSafeInteger(data.end_index) || (data.end_index as number) < 0
        || (data.end_index as number) > (data.history_count as number) || (data.end_index as number) > startIndex + limit) throw new Error("Invalid history page range");
      for (const raw of data.rows as Record<string, unknown>[]) {
        if (typeof raw.content !== "string" && !Array.isArray(raw.content)) throw new Error("Invalid history page content");
      }
      return data as unknown as HistoryPageResponseDto;
    },
  );
}

export function fetchHistoryResources(
  sessionId: string,
  signal: AbortSignal,
): Promise<HistoryResourcesResponseDto> {
  return requestJson(
    `/api/sessions/${encodeURIComponent(sessionId)}/history/resources`,
    signal,
    undefined,
    (value) => {
      const data = responseObject(value, sessionId);
      if (!Array.isArray(data.images) || !Array.isArray(data.downloads)) throw new Error("Invalid history resources");
      for (const raw of [...data.images, ...data.downloads]) {
        if (!raw || typeof raw !== "object" || typeof raw.resource_id !== "string" || typeof raw.url !== "string") throw new Error("Invalid history resource identity");
      }
      if (data.images.some((entry) => typeof entry.alt !== "string") || data.downloads.some((entry) => typeof entry.filename !== "string"
        || (entry.size !== undefined && entry.size !== null && (typeof entry.size !== "number" || !Number.isFinite(entry.size) || entry.size < 0)))) throw new Error("Invalid history resource fields");
      return data as unknown as HistoryResourcesResponseDto;
    },
  );
}
