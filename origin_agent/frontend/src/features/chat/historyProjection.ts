import type { ChatMessage } from "../../types";
import type { HistoryContentRowDto, HistorySkeletonRowDto } from "./types";
import { historyToolCardToChatMessage } from "./toolCards";

export function historyContentRowToChatMessage(row: HistoryContentRowDto): ChatMessage {
  if (row.tool_card) {
    return historyToolCardToChatMessage(row.row_id, row.history_index, row.character_name, row.tool_card);
  }
  const role = row.role === "user"
    ? "user"
    : row.role === "assistant"
      ? "assistant"
      : row.role === "tool"
        ? "tool"
        : row.role === "system"
          ? "system"
          : "error";
  return {
    id: row.row_id,
    role,
    content: row.content,
    messageIndex: row.history_index,
    characterName: row.character_name ?? undefined,
    visibleCharacters: row.visible_characters ?? undefined,
    responseCharacters: row.response_characters ?? undefined,
    messageSuffix: row.message_suffix ?? undefined,
    dynamicMessageSuffix: row.dynamic_message_suffix ?? undefined,
    reasoningContent: row.reasoning_content ?? undefined,
    requiresResponse: row.requires_response ?? undefined,
    toolName: row.tool_name ?? undefined,
    toolArgs: row.tool_args_raw ? undefined : (row.tool_args ?? undefined),
    toolArgsRawMap: undefined,
    activeToolCallKey: undefined,
    toolCallMeta: row.tool_call_meta ?? undefined,
    reasoningDuration: row.metrics?.reasoning_duration_ms,
    contentDuration: row.metrics?.content_duration_ms,
    completionTokens: row.metrics?.completion_tokens,
    tokensPerSecond: row.metrics?.tokens_per_second,
    isSystemStatus: row.is_system_status,
  };
}

export type HistorySkeletonVisualKind = "user" | "assistant" | "tool" | "system";

export function skeletonClassFor(row: HistorySkeletonRowDto): HistorySkeletonVisualKind {
  if (row.is_system_status || row.role === "system") return "system";
  if (row.row_kind === "tool_card" || row.role === "tool") return "tool";
  if (row.role === "user") return "user";
  return "assistant";
}

export function historyIndexRangeForRows(
  rows: HistorySkeletonRowDto[],
  startRow: number,
  endRow: number,
): { startIndex: number; limit: number } | null {
  if (rows.length === 0) return null;
  const start = Math.max(0, Math.min(startRow, rows.length - 1));
  const end = Math.max(start, Math.min(endRow, rows.length - 1));
  let min = Number.POSITIVE_INFINITY;
  let max = -1;
  for (let index = start; index <= end; index += 1) {
    const historyIndex = rows[index].history_index;
    min = Math.min(min, historyIndex);
    max = Math.max(max, historyIndex);
  }
  if (!Number.isFinite(min) || max < min) return null;
  return { startIndex: min, limit: max - min + 1 };
}
