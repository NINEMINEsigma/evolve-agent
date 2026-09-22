import { describe, expect, it } from "vitest";
import { mergeToolCard, toolCardLiveId, toolCardSummary } from "./toolCards";

describe("toolCards", () => {
  it("uses one live id per tool_call_id", () => {
    expect(toolCardLiveId("abc")).toBe("tool-card:abc");
  });

  it("keeps completed state against stale running updates", () => {
    const current = {
      request: { toolCallId: "abc", toolName: "Read" },
      status: "succeeded" as const,
      result: { content: "ok" },
    };
    const merged = mergeToolCard(current, { status: "running" });
    expect(merged.status).toBe("succeeded");
  });

  it("summarizes missing results explicitly", () => {
    expect(toolCardSummary({
      request: { toolCallId: "abc", toolName: "Read" },
      status: "missing_result",
    })).toContain("未返回结果");
  });
});
