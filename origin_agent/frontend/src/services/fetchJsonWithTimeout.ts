/**
 * Cancellable fetch helper whose hard deadline covers the response body and
 * decode step, not just the response headers. Unlike fetchWithTimeout (which
 * only guards the header handshake), this helper aborts the whole read and can
 * be externally cancelled; timeouts surface as RequestTimeoutError and
 * external cancellation as AbortError.
 */
import { RequestTimeoutError } from "./fetchWithTimeout";
import { decodeHttpError } from "./httpErrors";

export interface FetchJsonWithTimeoutOptions {
  timeoutMs: number;
  phase: string;
  createHttpError?: (status: number, payload: unknown | null) => Error;
}

function abortError(): DOMException {
  return new DOMException("The operation was aborted", "AbortError");
}

export async function fetchJsonWithTimeout<T>(
  input: RequestInfo | URL,
  init: RequestInit,
  options: FetchJsonWithTimeoutOptions,
  decode: (value: unknown) => T,
): Promise<T> {
  const started = performance.now();
  const controller = new AbortController();
  const externalSignal = init.signal;
  let timedOut = false;
  const onExternalAbort = () => controller.abort(externalSignal?.reason);

  if (externalSignal?.aborted) throw abortError();
  externalSignal?.addEventListener("abort", onExternalAbort, { once: true });
  const timeoutError = () =>
    new RequestTimeoutError(options.phase, options.timeoutMs, performance.now() - started);
  const timer = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, options.timeoutMs);

  const checkDeadline = () => {
    if (timedOut || performance.now() - started >= options.timeoutMs) throw timeoutError();
    if (externalSignal?.aborted) throw abortError();
  };
  try {
    const response = await fetch(input, { ...init, signal: controller.signal, cache: "no-store" });
    const body = await response.text();
    checkDeadline();
    let payload: unknown;
    try {
      payload = JSON.parse(body);
    } catch (error) {
      checkDeadline();
      if (!(error instanceof SyntaxError)) throw error;
      if (!response.ok) {
        throw options.createHttpError?.(response.status, null)
          ?? decodeHttpError(response.status, null);
      }
      throw new Error("Invalid JSON response body");
    }
    checkDeadline();
    if (!response.ok) {
      throw options.createHttpError?.(response.status, payload)
        ?? decodeHttpError(response.status, payload);
    }
    const result = decode(payload);
    checkDeadline();
    return result;
  } catch (error) {
    if (timedOut || performance.now() - started >= options.timeoutMs) throw timeoutError();
    if (externalSignal?.aborted) throw abortError();
    throw error;
  } finally {
    window.clearTimeout(timer);
    externalSignal?.removeEventListener("abort", onExternalAbort);
  }
}