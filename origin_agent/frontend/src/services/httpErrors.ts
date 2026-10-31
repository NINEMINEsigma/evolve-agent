import labels from "./httpErrorLabels.json";

export type HttpErrorKind = "business" | "validation" | "http";
export interface HttpBusinessDetail {
  readonly code: string;
  readonly message: string;
  readonly [key: string]: unknown;
}
export interface HttpValidationIssue {
  readonly loc: readonly (string | number)[];
  readonly msg: string;
  readonly type: string;
  readonly [key: string]: unknown;
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function validationIssue(value: unknown): value is HttpValidationIssue {
  return record(value) && Array.isArray(value.loc)
    && value.loc.every((part) => typeof part === "string" || typeof part === "number")
    && typeof value.msg === "string" && typeof value.type === "string";
}

export class HttpResponseError extends Error {
  readonly status: number;
  readonly kind: HttpErrorKind;
  readonly code: string | null;
  readonly businessDetail: HttpBusinessDetail | null;
  readonly validationIssues: readonly HttpValidationIssue[] | null;
  readonly payload: unknown | null;

  constructor(status: number, payload: unknown | null, fallbackMessage?: string) {
    const detail: unknown = record(payload) ? payload.detail : null;
    const business = record(detail) && typeof detail.code === "string" && detail.code.length > 0
      && typeof detail.message === "string" && detail.message.length > 0
      ? detail as HttpBusinessDetail : null;
    const issues = status === 422 && Array.isArray(detail) && detail.length > 0 && detail.every(validationIssue)
      ? detail as HttpValidationIssue[] : null;
    const message = business?.message ?? (issues
      ? `${labels.validationFailed}: ${issues.map((issue) => `${issue.loc.join(".")}: ${issue.msg}`).join("; ")}`
      : fallbackMessage || `HTTP ${status}`);
    super(message);
    this.name = "HttpResponseError";
    this.status = status;
    this.kind = business ? "business" : issues ? "validation" : "http";
    this.code = business?.code ?? null;
    this.businessDetail = business;
    this.validationIssues = issues;
    this.payload = payload;
  }
}

export function decodeHttpError(status: number, payload: unknown | null, fallbackMessage?: string): HttpResponseError {
  return new HttpResponseError(status, payload, fallbackMessage);
}
export function decodeHttpErrorBody(status: number, body: string, fallbackMessage?: string): HttpResponseError {
  let payload: unknown = null;
  try { payload = JSON.parse(body); } catch (error) {
    if (!(error instanceof SyntaxError)) throw error;
  }
  return decodeHttpError(status, payload, fallbackMessage);
}
export function formatHttpError(error: HttpResponseError): string {
  return error.message;
}
export function isPreExecutionRejection(error: HttpResponseError): boolean {
  return error.kind === "validation" || error.businessDetail?.request_accepted === false;
}
