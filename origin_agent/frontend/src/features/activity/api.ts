import type {
  ActivityEvent,
  ActivityEventKind,
  ActivityEventPhase,
  ActivityEventStatus,
  ActivityOverview,
  ActivityStreamGap,
  ActivityStreamItem,
} from "./types";
import { fetchJsonWithTimeout } from "../../services/fetchJsonWithTimeout";

const ACTIVITY_KINDS: readonly ActivityEventKind[] = [
  "message_received", "agent_response", "tool_call",
];
const ACTIVITY_PHASES: readonly ActivityEventPhase[] = ["observed", "started", "completed"];
const ACTIVITY_STATUSES: readonly ActivityEventStatus[] = [
  "observed", "active", "succeeded", "failed", "denied", "interrupted",
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function nonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function positiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 1;
}

function isActivityEvent(value: unknown): value is ActivityEvent {
  if (!isRecord(value)) return false;
  if (!positiveInteger(value.sequence) || typeof value.timestamp !== "string") return false;
  if (!ACTIVITY_KINDS.includes(value.kind as ActivityEventKind)) return false;
  if (!ACTIVITY_PHASES.includes(value.phase as ActivityEventPhase)) return false;
  if (!ACTIVITY_STATUSES.includes(value.status as ActivityEventStatus)) return false;
  if (typeof value.session_id !== "string" || value.session_id.length === 0) return false;
  if (!Array.isArray(value.input_sequences) || !value.input_sequences.every(positiveInteger)) return false;
  if (value.input_sequences.some((item, index, items) => index > 0 && item <= items[index - 1])) return false;
  if (value.duration_ms !== null && !nonNegativeInteger(value.duration_ms)) return false;
  if (value.activity_id !== null && typeof value.activity_id !== "string") return false;
  if (value.stream_id !== null && typeof value.stream_id !== "string") return false;
  if (value.tool_call_id !== null && typeof value.tool_call_id !== "string") return false;
  if (value.character_name !== null && typeof value.character_name !== "string") return false;
  if (value.tool_name !== null && typeof value.tool_name !== "string") return false;
  return true;
}

function isActivityGap(value: unknown): value is ActivityStreamGap {
  return isRecord(value)
    && value.type === "gap"
    && nonNegativeInteger(value.dropped)
    && value.dropped >= 1
    && typeof value.timestamp === "string";
}

export function decodeActivityStreamItem(value: unknown): ActivityStreamItem | null {
  if (isActivityEvent(value)) return value;
  if (isActivityGap(value)) return value;
  return null;
}

function decodeOverview(value: unknown): ActivityOverview {
  if (!isRecord(value)
    || !nonNegativeInteger(value.session_count)
    || !nonNegativeInteger(value.active_loop_count)
    || !nonNegativeInteger(value.tool_count)
    || !nonNegativeInteger(value.toolset_count)) {
    throw new Error("Activity overview response is invalid");
  }
  return {
    session_count: value.session_count,
    active_loop_count: value.active_loop_count,
    tool_count: value.tool_count,
    toolset_count: value.toolset_count,
  };
}

export function fetchActivityOverview(signal: AbortSignal): Promise<ActivityOverview> {
  return fetchJsonWithTimeout(
    "/api/activity/overview",
    { signal },
    { timeoutMs: 15_000, phase: "activity-overview" },
    decodeOverview,
  );
}
