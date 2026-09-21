export interface FetchTimeoutOptions {
  timeoutMs: number;
  phase: string;
}

export class RequestTimeoutError extends Error {
  readonly phase: string;
  readonly timeoutMs: number;
  readonly elapsedMs: number;

  constructor(phase: string, timeoutMs: number, elapsedMs: number) {
    super(`${phase} 请求等待 ${Math.round(elapsedMs)}ms 后超时`);
    this.name = "RequestTimeoutError";
    this.phase = phase;
    this.timeoutMs = timeoutMs;
    this.elapsedMs = elapsedMs;
  }
}

function abortError(): DOMException {
  return new DOMException("The operation was aborted", "AbortError");
}

/** 使用内部 AbortController 为 fetch 增加可区分的硬截止。 */
export async function fetchWithTimeout(
  input: RequestInfo | URL,
  init: RequestInit = {},
  options: FetchTimeoutOptions,
): Promise<Response> {
  const started = performance.now();
  const controller = new AbortController();
  const externalSignal = init.signal;
  let timedOut = false;
  const onExternalAbort = () => controller.abort(externalSignal?.reason);

  if (externalSignal?.aborted) throw abortError();
  externalSignal?.addEventListener("abort", onExternalAbort, { once: true });
  const timer = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, options.timeoutMs);

  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } catch (error) {
    if (timedOut) {
      throw new RequestTimeoutError(
        options.phase,
        options.timeoutMs,
        performance.now() - started,
      );
    }
    if (externalSignal?.aborted) throw abortError();
    throw error;
  } finally {
    window.clearTimeout(timer);
    externalSignal?.removeEventListener("abort", onExternalAbort);
  }
}
