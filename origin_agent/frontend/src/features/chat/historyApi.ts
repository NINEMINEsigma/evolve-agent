import type {
  HistoryPageResponseDto,
  HistoryResourcesResponseDto,
  HistorySkeletonResponseDto,
} from "./types";
import { chatTelemetry } from "./chatTelemetry";
import type { ClientDiagnosticPhase } from "../../types";
import { TIMING } from "../../constants/timing";
import { fetchWithTimeout, RequestTimeoutError } from "../../services/fetchWithTimeout";

export class ChatHistoryRequestError extends Error {
  readonly status: number;
  readonly retryable: boolean;

  constructor(message: string, status: number, retryable: boolean) {
    super(message);
    this.name = "ChatHistoryRequestError";
    this.status = status;
    this.retryable = retryable;
  }
}

async function requestJson<T>(
  url: string,
  signal: AbortSignal,
  phase?: ClientDiagnosticPhase,
): Promise<T> {
  const started = performance.now();
  chatTelemetry.record({
    time: Date.now(),
    kind: "history_request",
  });
  try {
    const response = phase
      ? await fetchWithTimeout(
          url,
          { signal },
          { timeoutMs: TIMING.CRITICAL_REQUEST_TIMEOUT, phase },
        )
      : await fetch(url, { signal });
    const data = await response.json().catch(() => ({}));
    chatTelemetry.record({
      time: Date.now(),
      kind: "history_response",
      durationMs: performance.now() - started,
      status: response.status,
    });
    if (!response.ok) {
      const detail = typeof data?.detail === "string"
        ? data.detail
        : typeof data?.error === "string"
          ? data.error
          : `HTTP ${response.status}`;
      throw new ChatHistoryRequestError(
        detail,
        response.status,
        response.status >= 500 || response.status === 408 || response.status === 429,
      );
    }
    return data as T;
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
  );
}

export function fetchHistoryResources(
  sessionId: string,
  signal: AbortSignal,
): Promise<HistoryResourcesResponseDto> {
  return requestJson(
    `/api/sessions/${encodeURIComponent(sessionId)}/history/resources`,
    signal,
  );
}
