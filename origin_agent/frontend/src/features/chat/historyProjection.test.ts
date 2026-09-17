import { describe, expect, it } from "vitest";
import { historyContentRowToChatMessage, historyIndexRangeForRows } from "./historyProjection";
import type { HistoryContentRowDto, HistorySkeletonRowDto } from "./types";

describe("historyProjection", () => {
  it("preserves stable row and History indices", () => {
    const row: HistoryContentRowDto = {
      row_id: "history:7:message",
      history_index: 7,
      row_kind: "message",
      role: "assistant",
      character_name: "main-agent",
      is_system_status: false,
      content: "hello",
    };
    const message = historyContentRowToChatMessage(row);
    expect(message.id).toBe(row.row_id);
    expect(message.messageIndex).toBe(7);
  });

  it("maps visible rows to the inclusive History range", () => {
    const rows: HistorySkeletonRowDto[] = [
      { row_id: "history:1:message", history_index: 1, row_kind: "message", role: "assistant", is_system_status: false },
      { row_id: "history:1:tool:0", history_index: 1, row_kind: "tool_call", role: "tool", tool_index: 0, is_system_status: false },
      { row_id: "history:4:message", history_index: 4, row_kind: "message", role: "user", is_system_status: false },
    ];
    expect(historyIndexRangeForRows(rows, 0, 2)).toEqual({ startIndex: 1, limit: 4 });
  });
});
