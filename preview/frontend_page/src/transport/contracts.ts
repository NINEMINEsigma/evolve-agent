export type {
  HistorySkeletonResponseDto, HistoryPageResponseDto, HistoryResourcesResponseDto,
} from "@origin/features/chat/types";
export type { SessionMediaListResponseDto, SessionMediaUpdateResponseDto } from "@origin/features/sessionMedia/types";
export type { SessionFileChangesSummaryDto, SessionFileChangesPageDto } from "@origin/features/sessionFileChanges/types";
export type { SessionVariablePoolResponseDto } from "@origin/features/sessionVariables/types";
export type { SessionRuntimeStatus, SessionLlmProfileState } from "@origin/types";

import type { HttpValidationIssue } from "@origin/services/httpErrors";

export class PreviewHttpError extends Error {
  readonly detail: Readonly<Record<string, unknown>> & { readonly code: string; readonly message: string };
  constructor(readonly status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.name = "PreviewHttpError";
    this.detail = { ...details, code, message };
  }
}
export class PreviewValidationError extends Error {
  constructor(readonly issues: readonly HttpValidationIssue[]) {
    super(issues.map((issue) => `${issue.loc.join(".")}: ${issue.msg}`).join("; "));
    this.name = "PreviewValidationError";
  }
}
export interface PreviewActionResponse { accepted: boolean }
export interface PreviewMutationResponse { updated: boolean }
export interface PreviewDeleteResponse { deleted: boolean; history_count?: number }
export interface PreviewMetadataRequest { title?: string; tags?: string[] }
export interface PreviewFileWriteRequest { path: string; content: string; expected_version: string | null; operation_id: string }

export function objectBody(value: unknown, location: readonly (string | number)[] = ["body"]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new PreviewValidationError([{ loc: location, msg: "Expected an object body", type: "model_attributes_type" }]);
  return value as Record<string, unknown>;
}
export async function readBody(request: Request, location: readonly (string | number)[] = ["body"]): Promise<Record<string, unknown>> {
  if (!request.body) return {};
  try { return objectBody(await request.json(), location); }
  catch (error) {
    if (error instanceof SyntaxError) throw new PreviewValidationError([{ loc: [...location, 0], msg: "Invalid JSON request body", type: "json_invalid" }]);
    throw error;
  }
}
export function text(value: unknown, location: readonly (string | number)[] = ["body"]): string {
  if (typeof value !== "string") throw new PreviewValidationError([{ loc: location, msg: "Expected a string", type: "string_type" }]);
  return value;
}
export function integer(value: unknown, minimum = 0, location: readonly (string | number)[] = ["body"]): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum) throw new PreviewValidationError([{ loc: location, msg: "Invalid integer", type: "greater_than_equal" }]);
  return value;
}
export function strings(value: unknown, location: readonly (string | number)[] = ["body"]): string[] {
  if (!Array.isArray(value)) throw new PreviewValidationError([{ loc: location, msg: "Expected strings", type: "list_type" }]);
  return value.map((entry: unknown, index) => text(entry, [...location, index]));
}
export function flag(value: unknown, location: readonly (string | number)[] = ["body"]): boolean {
  if (typeof value !== "boolean") throw new PreviewValidationError([{ loc: location, msg: "Expected a boolean", type: "bool_type" }]);
  return value;
}
export function queryInteger(url: URL, key: string, fallback: number, location: readonly (string | number)[] = ["query", key], minimum = 0, maximum?: number): number {
  const raw = url.searchParams.get(key);
  const value = raw === null ? fallback : /^\d+$/.test(raw) ? Number(raw) : NaN;
  const result = integer(value, minimum, location);
  if (maximum !== undefined && result > maximum) throw new PreviewValidationError([{ loc: location, msg: "Integer exceeds the upper limit", type: "less_than_equal" }]);
  return result;
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
