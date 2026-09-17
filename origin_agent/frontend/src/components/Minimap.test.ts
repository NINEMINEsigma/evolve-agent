import { describe, expect, it } from "vitest";
import { minimapIndexFromRatio, minimapRoleBuckets } from "./Minimap";

describe("logical Minimap", () => {
  it("maps pointer ratios to bounded logical indices", () => {
    expect(minimapIndexFromRatio(0, 100)).toBe(0);
    expect(minimapIndexFromRatio(0.5, 100)).toBe(50);
    expect(minimapIndexFromRatio(1, 100)).toBe(99);
  });

  it("aggregates dominant roles into canvas buckets", () => {
    expect(minimapRoleBuckets(["user", "assistant", "assistant", "tool"], 2)).toEqual([
      "user",
      "assistant",
    ]);
  });
});
