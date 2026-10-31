import type {
  DynamicSandboxDirectoryPickResponse,
  DynamicSandboxSpace,
  DynamicSandboxSpacesResponse,
} from "../types";
import { fetchJsonWithTimeout } from "./fetchJsonWithTimeout";
import { decodeHttpErrorBody } from "./httpErrors";

const SPACES_TIMEOUT_MS = 15_000;

async function requestJson<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
  const body = await response.text();
  if (!response.ok) throw decodeHttpErrorBody(response.status, body);
  const payload: unknown = JSON.parse(body);
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw new Error("Invalid sandbox space response");
  return payload as T;
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
  return fetchJsonWithTimeout("/api/sandbox-spaces", { signal },
    { timeoutMs: SPACES_TIMEOUT_MS, phase: "sandbox-spaces" }, decodeSpacesResponse);
}

export async function createDynamicSandboxSpace(
  space: DynamicSandboxSpace,
): Promise<DynamicSandboxSpace> {
  const data = await requestJson<{ space: DynamicSandboxSpace }>("/api/sandbox-spaces", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(space),
  });
  if (!data.space || data.space.name !== space.name || typeof data.space.path !== "string"
    || typeof data.space.description !== "string" || typeof data.space.is_readonly !== "boolean") throw new Error("Invalid sandbox space mutation response");
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
  if (!data.space || data.space.name !== space.name || typeof data.space.path !== "string"
    || typeof data.space.description !== "string" || typeof data.space.is_readonly !== "boolean") throw new Error("Invalid sandbox space mutation response");
  return data.space;
}

export async function removeDynamicSandboxSpace(name: string): Promise<boolean> {
  const data = await requestJson<{ removed: boolean }>(
    `/api/sandbox-spaces/${encodeURIComponent(name)}`,
    { method: "DELETE" },
  );
  if (data.removed !== true) throw new Error("Invalid sandbox space delete response");
  return data.removed;
}

export async function pickDynamicSandboxDirectory(): Promise<string | null> {
  const data = await requestJson<DynamicSandboxDirectoryPickResponse>(
    "/api/sandbox-spaces/pick-directory",
    { method: "POST" },
  );
  if (typeof data.selected !== "boolean") throw new Error("Invalid directory picker response");
  if (!data.selected) return null;
  if (typeof data.path !== "string" || !data.path) {
    throw new Error("目录选择器返回的路径无效");
  }
  return data.path;
}
