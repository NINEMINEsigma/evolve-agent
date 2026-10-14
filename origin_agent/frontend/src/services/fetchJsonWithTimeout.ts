/**
 * Cancellable fetch helper whose hard deadline covers the response body and
 * decode step, not just the response headers. Unlike fetchWithTimeout (which
 * only guards the header handshake), this helper aborts the whole read and can
 * be externally cancelled; timeouts surface as RequestTimeoutError and
 * external cancellation as AbortError.
 */
import { RequestTimeoutError } from "./fetchWithTimeout";

export interface FetchJsonWithTimeoutOptions {
  timeoutMs: number;
  phase: string;
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

  try {
    const response = await fetch(input, { ...init, signal: controller.signal, cache: "no-store" });
    const body = await response.text();
    let payload: unknown;
    try {
      payload = JSON.parse(body);
    } catch {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      throw new Error("Invalid JSON response body");
    }
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return decode(payload);
  } catch (error) {
    if (timedOut) throw timeoutError();
    if (externalSignal?.aborted) throw abortError();
    throw error;
  } finally {
    window.clearTimeout(timer);
    externalSignal?.removeEventListener("abort", onExternalAbort);
  }
}