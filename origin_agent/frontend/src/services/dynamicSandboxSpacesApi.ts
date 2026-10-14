import type {
  DynamicSandboxDirectoryPickResponse,
  DynamicSandboxSpace,
  DynamicSandboxSpacesResponse,
} from "../types";
import { RequestTimeoutError } from "./fetchWithTimeout";

const SPACES_TIMEOUT_MS = 15_000;

async function responseError(response: Response): Promise<Error> {
  const data = await response.json().catch(() => ({}));
  const detail = (data as { detail?: unknown }).detail;
  const message = typeof detail === "string"
    ? detail
    : `请求失败 (${response.status})`;
  return new Error(message);
}

async function requestJson<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
  if (!response.ok) throw await responseError(response);
  return response.json() as Promise<T>;
}

function decodeSpacesResponse(payload: unknown): DynamicSandboxSpacesResponse {
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("服务端返回的动态沙盒空间列表格式无效");
  }
  const spaces = (payload as Record<string, unknown>).spaces;
  if (!Array.isArray(spaces)) {
    throw new Error("服务端返回的动态沙盒空间列表格式无效");
  }
  for (const entry of spaces) {
    if (entry === null || typeof entry !== "object" || Array.isArray(entry)) {
      throw new Error("服务端返回的动态沙盒空间列表格式无效");
    }
    const item = entry as Record<string, unknown>;
    if (typeof item.name !== "string" || typeof item.path !== "string"
      || typeof item.description !== "string" || typeof item.is_readonly !== "boolean"
      || typeof item.available !== "boolean") {
      throw new Error("服务端返回的动态沙盒空间列表格式无效");
    }
  }
  return { spaces } as DynamicSandboxSpacesResponse;
}

/** 列表 GET：完整 JSON 截止 + 外部取消 + 必要字段校验；其他 CRUD 保持原样。 */
export async function listDynamicSandboxSpaces(signal?: AbortSignal): Promise<DynamicSandboxSpacesResponse> {
  const started = performance.now();
  const controller = new AbortController();
  let timedOut = false;
  if (signal?.aborted) throw new DOMException("The operation was aborted", "AbortError");
  const onAbort = () => controller.abort();
  signal?.addEventListener("abort", onAbort, { once: true });
  const timer = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, SPACES_TIMEOUT_MS);
  try {
    const response = await fetch("/api/sandbox-spaces", { cache: "no-store", signal: controller.signal });
    const body = await response.text();
    if (timedOut) throw new RequestTimeoutError("sandbox-spaces", SPACES_TIMEOUT_MS, performance.now() - started);
    if (!response.ok) throw new Error(`请求失败 (${response.status})`);
    let payload: unknown;
    try { payload = JSON.parse(body); } catch { throw new Error("服务端返回的动态沙盒空间列表格式无效"); }
    if (timedOut) throw new RequestTimeoutError("sandbox-spaces", SPACES_TIMEOUT_MS, performance.now() - started);
    return decodeSpacesResponse(payload);
  } catch (failure) {
    if (timedOut) throw new RequestTimeoutError("sandbox-spaces", SPACES_TIMEOUT_MS, performance.now() - started);
    if (signal?.aborted) throw new DOMException("The operation was aborted", "AbortError");
    throw failure;
  } finally {
    window.clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}

export async function createDynamicSandboxSpace(
  space: DynamicSandboxSpace,
): Promise<DynamicSandboxSpace> {
  const data = await requestJson<{ space: DynamicSandboxSpace }>("/api/sandbox-spaces", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(space),
  });
  return data.space;
}

export async function updateDynamicSandboxSpace(
  name: string,
  space: DynamicSandboxSpace,
): Promise<DynamicSandboxSpace> {
  if (name !== space.name) {
    throw new Error("动态沙盒空间名称不可修改");
  }
  const data = await requestJson<{ space: DynamicSandboxSpace }>(
    `/api/sandbox-spaces/${encodeURIComponent(name)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(space),
    },
  );
  return data.space;
}

export async function removeDynamicSandboxSpace(name: string): Promise<boolean> {
  const data = await requestJson<{ removed: boolean }>(
    `/api/sandbox-spaces/${encodeURIComponent(name)}`,
    { method: "DELETE" },
  );
  return data.removed;
}

export async function pickDynamicSandboxDirectory(): Promise<string | null> {
  const data = await requestJson<DynamicSandboxDirectoryPickResponse>(
    "/api/sandbox-spaces/pick-directory",
    { method: "POST" },
  );
  if (!data.selected) return null;
  if (typeof data.path !== "string" || !data.path) {
    throw new Error("目录选择器返回的路径无效");
  }
  return data.path;
}
