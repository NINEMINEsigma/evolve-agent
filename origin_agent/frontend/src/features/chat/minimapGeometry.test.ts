import { describe, expect, it } from "vitest";
import {
  buildHeightWeightedSegments,
  minimapDragTarget,
  minimapHitGeometry,
  minimapViewportGeometry,
  measuredHistoryRowHeights,
  normalizeScrollMetrics,
  scrollTopToLogicalRange,
} from "./minimapGeometry";

const skeleton = [
  { row_id: "history:0:message", history_index: 0, row_kind: "message" as const, role: "user", is_system_status: false },
  { row_id: "history:1:message", history_index: 1, row_kind: "message" as const, role: "assistant", is_system_status: false },
];

describe("physical Minimap geometry", () => {
  it("maps viewport to exact physical proportions", () => {
    expect(minimapViewportGeometry({ scrollTop: 400, scrollHeight: 2000, viewportHeight: 500 }, 200))
      .toEqual({ top: 40, height: 50 });
  });

  it("covers the track when scrolling is impossible", () => {
    const metrics = { scrollTop: 999, scrollHeight: 500, viewportHeight: 500 };
    expect(minimapViewportGeometry(metrics, 100)).toEqual({ top: 0, height: 100 });
    expect(minimapDragTarget(80, 0, 100, { top: 0, height: 100 }, 50, metrics).scrollTop).toBe(0);
  });

  it("keeps thin visual highlights unchanged while expanding hit geometry", () => {
    const viewport = { top: 60, height: 2 };
    expect(minimapHitGeometry(viewport, 200, 16)).toEqual({ top: 53, height: 16 });
    expect(viewport.height).toBe(2);
  });

  it("preserves grab offset and clamps the physical target", () => {
    const metrics = { scrollTop: 250, scrollHeight: 1000, viewportHeight: 200 };
    const viewport = minimapViewportGeometry(metrics, 100);
    const target = minimapDragTarget(60, 0, 100, viewport, 5, metrics);
    expect(target.minimapTop).toBe(55);
    expect(target.scrollTop).toBe(550);
    expect(minimapDragTarget(999, 0, 100, viewport, 5, metrics).scrollTop).toBe(800);
  });

  it("weights canvas rows by measured height without changing physical scrolling", () => {
    const segments = buildHeightWeightedSegments(skeleton, [], {
      "history:0:message": 100,
      "history:1:message": 900,
    });
    expect(segments[1].endRatio - segments[1].startRatio)
      .toBeGreaterThan(segments[0].endRatio - segments[0].startRatio);
    expect(scrollTopToLogicalRange(
      { scrollTop: 600, scrollHeight: 1120, viewportHeight: 200 },
      segments,
    ).endIndex).toBe(1);
  });

  it("maps measured heights, fallback heights and live rows into one background", () => {
    const liveRows = [{
      id: "live:1",
      version: 1,
      message: { role: "assistant" as const, id: "live:1", content: "response" },
      streaming: true,
      frozen: false,
    }];
    const segments = buildHeightWeightedSegments(skeleton, liveRows, {
      "history:0:message": 180,
      "live:1": 400,
    });
    expect(segments).toHaveLength(3);
    expect(segments[0].weight).toBe(180);
    expect(segments[1].weight).toBe(110); // assistant skeleton 104px + 6px row gap
    expect(segments[2].weight).toBe(400);
    expect(scrollTopToLogicalRange(
      { scrollTop: 410, scrollHeight: 810, viewportHeight: 100 },
      segments,
    )).toEqual({ startIndex: 2, endIndex: 2 });
  });

  it("skips Virtuoso items without data or valid size", () => {
    expect(measuredHistoryRowHeights([
      { index: 0, offset: 0, size: 180 },
      { index: 1, offset: 180, size: 70, data: skeleton[0] },
      { index: 2, offset: 250, size: NaN, data: skeleton[1] },
    ])).toEqual([{ id: "history:0:message", height: 70 }]);
  });

  it("never creates negative geometry for zero-height highlights", () => {
    const viewport = { top: 100, height: 0 };
    const hit = minimapHitGeometry(viewport, 100, 16);
    expect(hit).toEqual({ top: 84, height: 16 });
    expect(minimapDragTarget(999, 0, 100, viewport, 0,
      { scrollTop: 0, scrollHeight: 100, viewportHeight: 0 },
    ).scrollTop).toBe(100);
  });

  it("uses safe values for invalid metrics", () => {
    expect(normalizeScrollMetrics({ scrollTop: Infinity, scrollHeight: NaN, viewportHeight: -1 }))
      .toEqual({ scrollTop: 0, scrollHeight: 0, viewportHeight: 0 });
    expect(scrollTopToLogicalRange({ scrollTop: 0, scrollHeight: 0, viewportHeight: 0 }, []))
      .toEqual({ startIndex: 0, endIndex: 0 });
  });
});
