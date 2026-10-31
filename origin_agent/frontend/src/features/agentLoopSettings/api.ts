import { TIMING } from "../../constants/timing";
import { fetchJsonWithTimeout } from "../../services/fetchJsonWithTimeout";
import { decodeHttpError, HttpResponseError, isPreExecutionRejection } from "../../services/httpErrors";
import { agentLoopSettingsLabels as labels } from "./labels";
import type { AgentLoopSettingsState } from "./types";

const endpoint = "/api/agent-loop/settings";

export class AgentLoopSettingsHttpError extends Error {
  readonly status: number;
  constructor(readonly httpError: HttpResponseError) {
    super(httpError.message);
    this.name = "AgentLoopSettingsHttpError";
    this.status = httpError.status;
  }

  get uncertain(): boolean {
    return !isPreExecutionRejection(this.httpError);
  }
}

function object(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(labels.protocolError);
  }
  return value as Record<string, unknown>;
}

function positiveInteger(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 1) {
    throw new Error(labels.protocolError);
  }
  return value;
}

export function decodeAgentLoopSettingsState(value: unknown): AgentLoopSettingsState {
  const data = object(value);
  const fields = ["max_tool_turns", "effective_max_tool_turns", "default_max_tool_turns"];
  if (Object.keys(data).length !== fields.length || Object.keys(data).some((key) => !fields.includes(key))) {
    throw new Error(labels.protocolError);
  }
  const configured = data.max_tool_turns === null ? null : positiveInteger(data.max_tool_turns);
  const effective = positiveInteger(data.effective_max_tool_turns);
  const fallback = positiveInteger(data.default_max_tool_turns);
  if (effective !== (configured ?? fallback)) throw new Error(labels.protocolError);
  return {
    max_tool_turns: configured,
    effective_max_tool_turns: effective,
    default_max_tool_turns: fallback,
  };
}

export function readAgentLoopSettings(signal?: AbortSignal): Promise<AgentLoopSettingsState> {
  return fetchJsonWithTimeout(endpoint, { method: "GET", signal, cache: "no-store" }, {
    timeoutMs: TIMING.CRITICAL_REQUEST_TIMEOUT,
    phase: "agent-loop-settings-read",
    createHttpError: (status, payload) => new AgentLoopSettingsHttpError(decodeHttpError(status, payload)),
  }, decodeAgentLoopSettingsState);
}

export function updateAgentLoopSettings(
  maxToolTurns: number | null, signal?: AbortSignal,
): Promise<AgentLoopSettingsState> {
  return fetchJsonWithTimeout(endpoint, {
    method: "PUT", signal, cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ max_tool_turns: maxToolTurns }),
  }, {
    timeoutMs: TIMING.CRITICAL_REQUEST_TIMEOUT,
    phase: "agent-loop-settings-save",
    createHttpError: (status, payload) => new AgentLoopSettingsHttpError(decodeHttpError(status, payload)),
  }, decodeAgentLoopSettingsState);
}
