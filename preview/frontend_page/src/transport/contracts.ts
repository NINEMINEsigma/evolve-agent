export type {
  HistorySkeletonResponseDto, HistoryPageResponseDto, HistoryResourcesResponseDto,
} from "@origin/features/chat/types";
export type { SessionMediaListResponseDto, SessionMediaUpdateResponseDto } from "@origin/features/sessionMedia/types";
export type { SessionFileChangesSummaryDto, SessionFileChangesPageDto } from "@origin/features/sessionFileChanges/types";
export type { SessionVariablePoolResponseDto } from "@origin/features/sessionVariables/types";
export type { SessionRuntimeStatus, SessionLlmProfileState } from "@origin/types";

export class PreviewHttpError extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}
export interface PreviewActionResponse { accepted: boolean }
export interface PreviewMutationResponse { updated: boolean }
export interface PreviewDeleteResponse { deleted: boolean; history_count?: number }
export interface PreviewMetadataRequest { title?: string; tags?: string[] }
export interface PreviewFileWriteRequest { path: string; content: string; expected_version: string | null; operation_id: string }

export function objectBody(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new PreviewHttpError(422, "Expected an object body");
  return value as Record<string, unknown>;
}
export async function readBody(request: Request): Promise<Record<string, unknown>> {
  if (!request.body) return {};
  try { return objectBody(await request.json()); }
  catch (error) {
    if (error instanceof PreviewHttpError) throw error;
    throw new PreviewHttpError(422, "Invalid JSON request body");
  }
}
export function text(value: unknown): string {
  if (typeof value !== "string") throw new PreviewHttpError(422, "Expected a string");
  return value;
}
export function integer(value: unknown, minimum = 0): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum) throw new PreviewHttpError(422, "Invalid integer");
  return value;
}
export function strings(value: unknown): string[] {
  if (!Array.isArray(value) || value.some((entry) => typeof entry !== "string")) throw new PreviewHttpError(422, "Expected strings");
  return value as string[];
}
export function flag(value: unknown): boolean {
  if (typeof value !== "boolean") throw new PreviewHttpError(422, "Expected a boolean");
  return value;
}
export function queryInteger(url: URL, key: string, fallback: number): number {
  return url.searchParams.has(key) ? integer(Number(url.searchParams.get(key))) : fallback;
}
export function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json; charset=utf-8" } });
}

export class PreviewResourceResponse extends Response {
  constructor(body: BodyInit | null, init: ResponseInit, private readonly finalUrl: string) { super(body, init); }
  override get url(): string { return this.finalUrl; }
  override clone(): Response {
    if (this.bodyUsed) throw new TypeError("Response body is already consumed");
    const copy = super.clone();
    return new PreviewResourceResponse(copy.body, { status: copy.status, statusText: copy.statusText, headers: copy.headers }, this.finalUrl);
  }
}
