import type { ListItem } from "react-virtuoso";
import type { ChatRenderRow, ChatScrollMetrics } from "./types";

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

export function measuredHistoryRowHeights(
  items: ListItem<ChatRenderRow>[],
): Array<{ id: string; height: number }> {
  const entries: Array<{ id: string; height: number }> = [];
  for (const item of items) {
    const id = item.data?.renderId;
    if (!id || !Number.isFinite(item.size) || item.size <= 0) continue;
    entries.push({ id, height: item.size });
  }
  return entries;
}
