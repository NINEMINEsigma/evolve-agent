import type { PreviewRuntime } from "../types";
import { DEMO_ASSETS } from "../constants";
import { reportPreviewFault } from "../runtime/faults";
import { handleSessionRequest } from "./sessionRoutes";
import { handleConfigRequest } from "./configRoutes";
import { handleFileRequest } from "./fileRoutes";
import { PreviewHttpError, jsonResponse } from "./contracts";

const staticPaths = new Set<string>(Object.values(DEMO_ASSETS));
export function createPreviewFetch(runtime: PreviewRuntime, nativeFetch: typeof fetch): typeof fetch {
  return async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const absolute = typeof input === "string" ? new URL(input, location.href).href : input;
    const request = new Request(absolute, init);
    const url = new URL(request.url);
    request.signal.throwIfAborted();
    if (url.origin !== location.origin) {
      reportPreviewFault({ code: "external_fetch", path: url.pathname, message: "External requests are blocked" });
      throw new TypeError("Preview blocks external requests");
    }
    if (staticPaths.has(url.pathname) && ["GET", "HEAD"].includes(request.method)) return nativeFetch(request);
    runtime.pendingRequests += 1;
    try {
      const handlers = [handleSessionRequest, handleConfigRequest, handleFileRequest];
      for (const handler of handlers) {
        request.signal.throwIfAborted();
        const response = await handler(request, runtime);
        if (response !== null) return response;
      }
      reportPreviewFault({ code: "unknown_route", path: url.pathname, message: `Unregistered ${request.method} request` });
      return jsonResponse({ detail: "Unregistered preview endpoint" }, 501);
    } catch (error) {
      if (request.signal.aborted) throw request.signal.reason;
      if (error instanceof PreviewHttpError) return jsonResponse({ detail: error.message, error: error.message }, error.status);
      reportPreviewFault({ code: "http_handler", path: url.pathname, message: error instanceof Error ? error.message : "Preview request failed" });
      return jsonResponse({ detail: "Preview request handler failed" }, 500);
    } finally { runtime.pendingRequests -= 1; }
  };
}
