import type { RegenerateTrimPayload } from "./types";

export function isRegenerateTrimPayload(value: unknown): value is RegenerateTrimPayload {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const payload = value as Record<string, unknown>;
  return payload.regenerate_trim === true
    && typeof payload.message_index === "number"
    && Number.isSafeInteger(payload.message_index)
    && payload.message_index >= 0
    && typeof payload.keep_count === "number"
    && Number.isSafeInteger(payload.keep_count)
    && payload.keep_count > 0
    && Number.isSafeInteger(payload.message_index + 1)
    && payload.keep_count === payload.message_index + 1
    && (payload.message_suffix == null || typeof payload.message_suffix === "string")
    && (payload.dynamic_message_suffix == null || typeof payload.dynamic_message_suffix === "string");
}
