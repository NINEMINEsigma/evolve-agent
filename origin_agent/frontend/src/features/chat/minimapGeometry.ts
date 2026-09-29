import type { ListItem } from "react-virtuoso";
import {
  CHAT_BOTTOM_SAFE_SPACE_PX,
  HISTORY_ROW_GAP_PX,
  HISTORY_SKELETON_HEIGHTS,
} from "../../constants/history";
import { skeletonClassFor, type HistorySkeletonVisualKind } from "./historyProjection";
import type {
  ChatMinimapSegment,
  ChatScrollMetrics,
  ChatVisibleRange,
  HistorySkeletonRowDto,
  LiveChatRow,
} from "./types";

export interface MinimapViewportGeometry {
  top: number;
  height: number;
}

export interface MinimapDragTarget {
  minimapTop: number;
  scrollTop: number;
}

const finiteNonNegative = (value: number): number =>
  Number.isFinite(value) && value >= 0 ? value : 0;

export function normalizeScrollMetrics(metrics: ChatScrollMetrics): ChatScrollMetrics {
  const scrollHeight = finiteNonNegative(metrics.scrollHeight);
  const viewportHeight = Math.min(finiteNonNegative(metrics.viewportHeight), scrollHeight);
  const maxScrollTop = Math.max(0, scrollHeight - viewportHeight);
  return {
    scrollTop: Math.min(finiteNonNegative(metrics.scrollTop), maxScrollTop),
    scrollHeight,
    viewportHeight,
  };
}

export function minimapViewportGeometry(
  metrics: ChatScrollMetrics,
  minimapHeight: number,
): MinimapViewportGeometry {
  const normalized = normalizeScrollMetrics(metrics);
  const height = finiteNonNegative(minimapHeight);
  if (height === 0 || normalized.scrollHeight === 0) return { top: 0, height: 0 };
  return {
    top: normalized.scrollTop / normalized.scrollHeight * height,
    height: normalized.viewportHeight / normalized.scrollHeight * height,
  };
}

export function minimapHitGeometry(
  viewport: MinimapViewportGeometry,
  minimapHeight: number,
  minimumHitHeight: number,
): MinimapViewportGeometry {
  const rootHeight = finiteNonNegative(minimapHeight);
  const requestedHeight = Math.max(viewport.height, finiteNonNegative(minimumHitHeight));
  const height = Math.min(rootHeight, requestedHeight);
  const center = viewport.top + viewport.height / 2;
  const top = Math.max(0, Math.min(rootHeight - height, center - height / 2));
  return { top, height };
}

export function minimapDragTarget(
  pointerY: number,
  rootTop: number,
  minimapHeight: number,
  viewport: MinimapViewportGeometry,
  grabOffset: number,
  metrics: ChatScrollMetrics,
): MinimapDragTarget {
  const normalized = normalizeScrollMetrics(metrics);
  const height = finiteNonNegative(minimapHeight);
  const thumbHeight = Math.min(height, finiteNonNegative(viewport.height));
  const minimapTravel = Math.max(0, height - thumbHeight);
  const rawTop = finiteNonNegative(pointerY - rootTop - finiteNonNegative(grabOffset));
  const minimapTop = Math.max(0, Math.min(minimapTravel, rawTop));
  const progress = minimapTravel > 0 ? minimapTop / minimapTravel : 0;
  const scrollTravel = Math.max(0, normalized.scrollHeight - normalized.viewportHeight);
  return { minimapTop, scrollTop: progress * scrollTravel };
}

function visualRoleForLive(row: LiveChatRow): HistorySkeletonVisualKind {
  const role = row.message.role;
  if (role === "user") return "user";
  if (role === "tool") return "tool";
  if (role === "system" || role === "error") return "system";
  return "assistant";
}

export function buildHeightWeightedSegments(
  skeleton: HistorySkeletonRowDto[],
  liveRows: LiveChatRow[],
  rowHeights: Record<string, number>,
  topSafeSpacePx: number,
): ChatMinimapSegment[] {
  const rows = [
    ...skeleton.map((row) => {
      const role = skeletonClassFor(row);
      return {
        id: row.row_id,
        role,
        weight: rowHeights[row.row_id] ?? HISTORY_SKELETON_HEIGHTS[role] + HISTORY_ROW_GAP_PX,
      };
    }),
    ...liveRows.map((row) => {
      const role = visualRoleForLive(row);
      return {
        id: row.id,
        role,
        weight: rowHeights[row.id] ?? HISTORY_SKELETON_HEIGHTS[role] + HISTORY_ROW_GAP_PX,
      };
    }),
  ].map((row) => ({
    ...row,
    weight: Number.isFinite(row.weight) && row.weight > 0 ? row.weight : 1,
  }));

  const rowWeight = rows.reduce((sum, row) => sum + row.weight, 0);
  const topSafeSpace = finiteNonNegative(topSafeSpacePx);
  const totalWeight = topSafeSpace + rowWeight + CHAT_BOTTOM_SAFE_SPACE_PX;
  if (rows.length === 0 || totalWeight <= 0) return [];
  let cursor = topSafeSpace;
  return rows.map((row) => {
    const startRatio = cursor / totalWeight;
    cursor += row.weight;
    return {
      id: row.id,
      role: row.role,
      weight: row.weight,
      startRatio,
      endRatio: cursor / totalWeight,
    };
  });
}

export function measuredHistoryRowHeights(
  items: ListItem<HistorySkeletonRowDto>[],
): Array<{ id: string; height: number }> {
  const entries: Array<{ id: string; height: number }> = [];
  for (const item of items) {
    const id = item.data?.row_id;
    if (!id || !Number.isFinite(item.size) || item.size <= 0) continue;
    entries.push({ id, height: item.size });
  }
  return entries;
}

export function scrollTopToLogicalRange(
  metrics: ChatScrollMetrics,
  segments: ChatMinimapSegment[],
): ChatVisibleRange {
  if (segments.length === 0) return { startIndex: 0, endIndex: 0 };
  const normalized = normalizeScrollMetrics(metrics);
  if (normalized.scrollHeight <= 0) {
    return { startIndex: 0, endIndex: Math.max(0, segments.length - 1) };
  }
  const topRatio = normalized.scrollTop / normalized.scrollHeight;
  const bottomRatio = Math.min(
    1,
    (normalized.scrollTop + normalized.viewportHeight) / normalized.scrollHeight,
  );
  // 累计权重的比例单调递增，可以直接定位与物理视口相交的首末行。
  let lower = 0;
  let upper = segments.length;
  while (lower < upper) {
    const middle = Math.floor((lower + upper) / 2);
    if (segments[middle].endRatio < topRatio) lower = middle + 1;
    else upper = middle;
  }
  const startIndex = Math.min(lower, segments.length - 1);

  lower = startIndex;
  upper = segments.length;
  while (lower < upper) {
    const middle = Math.floor((lower + upper) / 2);
    if (segments[middle].startRatio <= bottomRatio) lower = middle + 1;
    else upper = middle;
  }
  return { startIndex, endIndex: Math.max(startIndex, lower - 1) };
}
