import type { CleanupReport, ShellInfo, ShellStopResult } from "../types";
import { decodeHttpErrorBody } from "./httpErrors";

function objectValue(payload: unknown): Record<string, unknown> {
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("Expected a JSON object");
  }
  return payload as Record<string, unknown>;
}

function decodeCleanupReport(payload: unknown): CleanupReport {
  const value = objectValue(payload);
  if (typeof value.complete !== "boolean" || !Array.isArray(value.pending_resources)) {
    throw new Error("Invalid cleanup report");
  }
  if (value.complete && value.pending_resources.length > 0) {
    throw new Error("Completed cleanup cannot list pending resources");
  }
  if (!value.complete && value.pending_resources.length === 0) {
    throw new Error("Pending cleanup requires resource identifiers");
  }
  return value as unknown as CleanupReport;
}

export function decodeShellInfo(payload: unknown, sessionId: string): ShellInfo {
  const item = objectValue(payload);
  if (item.session_id !== sessionId) throw new Error("Shell belongs to a different session");
  if (typeof item.shell_id !== "string" || typeof item.running !== "boolean") {
    throw new Error("Invalid shell entry");
  }
  const cleanup = item.cleanup == null ? null : decodeCleanupReport(item.cleanup);
  return { ...(item as unknown as ShellInfo), cleanup };
}

export function decodeShellStopResult(
  payload: unknown,
  sessionId: string,
  shellId: string,
): ShellStopResult {
  const value = objectValue(payload);
  const shell = decodeShellInfo(value.shell, sessionId);
  const cleanup = decodeCleanupReport(value.cleanup);
  if (shell.shell_id !== shellId || value.stopped !== cleanup.complete) {
    throw new Error("Shell stop result is inconsistent");
  }
  return { stopped: cleanup.complete, shell, cleanup };
}

export async function fetchSessionShells(
  sessionId: string,
  signal?: AbortSignal,
): Promise<ShellInfo[]> {
  const response = await fetch(`/api/sessions/${sessionId}/shells`, { signal });
  if (!response.ok) throw decodeHttpErrorBody(response.status, await response.text());
  const payload = objectValue(await response.json());
  if (!Array.isArray(payload.shells)) throw new Error("Shells payload is not an array");
  return payload.shells.map((entry) => decodeShellInfo(entry, sessionId));
}

export async function stopSessionShell(
  sessionId: string,
  shellId: string,
  signal?: AbortSignal,
): Promise<ShellStopResult> {
  const response = await fetch(`/api/sessions/${sessionId}/shells/${shellId}/stop`, {
    method: "POST",
    signal,
  });
  if (!response.ok) throw decodeHttpErrorBody(response.status, await response.text());
  return decodeShellStopResult(await response.json(), sessionId, shellId);
}
