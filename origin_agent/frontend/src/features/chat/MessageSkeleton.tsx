import { HISTORY_SKELETON_HEIGHTS } from "../../constants/history";
import { skeletonClassFor } from "./historyProjection";
import type { HistorySkeletonRowDto } from "./types";

export default function MessageSkeleton({ row }: { row: HistorySkeletonRowDto }) {
  const kind = skeletonClassFor(row);
  return (
    <div
      className={`chat-history-message-skeleton skeleton-${kind}`}
      style={{ minHeight: HISTORY_SKELETON_HEIGHTS[kind] }}
      data-history-row-id={row.row_id}
      aria-hidden="true"
    >
      <span className="chat-history-skeleton-avatar" />
      <span className="chat-history-skeleton-bubble" />
    </div>
  );
}
