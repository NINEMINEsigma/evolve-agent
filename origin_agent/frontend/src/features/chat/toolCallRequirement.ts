import type { ChatRuntimeState } from "./chatRuntimeStore";
import labels from "./toolCallRequirementLabels.json";

export const TOOL_CALL_REQUIREMENT_LABELS = {
  label: labels.label,
  idleHint: labels.idleHint,
  busyHint: labels.busyHint,
  subagentHint: labels.subagentHint,
  busyRegenerateNotice: labels.busyRegenerateNotice,
};

export function isMainSessionBusyForToolCall(
  state: Pick<ChatRuntimeState, "processing" | "mainSessionActivity">,
): boolean {
  return state.processing || state.mainSessionActivity !== null;
}

export function shouldRequireToolCall(
  state: Pick<ChatRuntimeState, "requireToolCall" | "processing" | "mainSessionActivity">,
  sendsToMain: boolean,
): boolean {
  return state.requireToolCall && sendsToMain && !isMainSessionBusyForToolCall(state);
}
