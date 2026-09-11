import type {
  DynamicSandboxDirectoryPickResponse,
  DynamicSandboxSpace,
  DynamicSandboxSpacesResponse,
} from "../types";

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

export async function listDynamicSandboxSpaces(): Promise<DynamicSandboxSpacesResponse> {
  const data = await requestJson<DynamicSandboxSpacesResponse>("/api/sandbox-spaces");
  if (!data || !Array.isArray(data.spaces)) {
    throw new Error("服务端返回的动态沙盒空间列表格式无效");
  }
  return data;
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
