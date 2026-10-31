import { STORAGE_KEYS } from "../constants/storage";
import { TIMING } from "../constants/timing";
import type { SessionLlmProfileState } from "../types";
import { fetchJsonWithTimeout } from "./fetchJsonWithTimeout";

export function sessionLlmSelectionKey(sessionId: string): string {
  return `${STORAGE_KEYS.SESSION_LLM_PROFILE_PREFIX}${encodeURIComponent(sessionId)}`;
}

export function readSessionLlmSelection(sessionId: string): string | undefined {
  if (!sessionId) return undefined;
  try {
    const stored = localStorage.getItem(sessionLlmSelectionKey(sessionId));
    if (stored === null) return undefined;
    const value: unknown = JSON.parse(stored);
    if (typeof value === "string") return value;
    removeSessionLlmSelection(sessionId);
  } catch {
    removeSessionLlmSelection(sessionId);
  }
  return undefined;
}

export function writeSessionLlmSelection(sessionId: string, name: string): boolean {
  if (!sessionId) return false;
  try {
    localStorage.setItem(sessionLlmSelectionKey(sessionId), JSON.stringify(name));
    return true;
  } catch { return false; }
}

export function removeSessionLlmSelection(sessionId: string): void {
  if (!sessionId) return;
  try { localStorage.removeItem(sessionLlmSelectionKey(sessionId)); } catch { /* 内存仍可继续使用。 */ }
}

/** 名称替换永不删除键；空字符串表示显式无配置。 */
export function replaceStoredSessionLlmSelections(oldName: string, newName: string): void {
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (!key?.startsWith(STORAGE_KEYS.SESSION_LLM_PROFILE_PREFIX)) continue;
      try {
        if (JSON.parse(localStorage.getItem(key) ?? "null") === oldName) {
          localStorage.setItem(key, JSON.stringify(newName));
        }
      } catch { /* 跳过损坏或不可写的单个条目。 */ }
    }
  } catch { /* 禁止存储时由 hook 的内存选择降级。 */ }
}

export async function fetchSessionLlmProfile(
  sessionId: string, signal: AbortSignal,
): Promise<SessionLlmProfileState> {
  return fetchJsonWithTimeout(`/api/sessions/${encodeURIComponent(sessionId)}/llm-profile`, { signal },
    { timeoutMs: TIMING.CRITICAL_REQUEST_TIMEOUT, phase: "session-llm-profile" }, (data) => {
      if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("Invalid session profile response");
      const value = data as Record<string, unknown>;
      if (value.session_id !== sessionId || typeof value.available !== "boolean"
        || (value.profile_name !== null && typeof value.profile_name !== "string")) {
        throw new Error("Session profile response does not match the request");
      }
      return value as unknown as SessionLlmProfileState;
    });
}
