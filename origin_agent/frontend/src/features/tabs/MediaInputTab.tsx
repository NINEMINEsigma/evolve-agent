import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactElement } from "react";
import { SESSION_MEDIA } from "../../constants/sessionMedia";
import MediaDetailsWindow from "../sessionMedia/MediaDetailsWindow";
import MediaGalleryTile from "../sessionMedia/MediaGalleryTile";
import { formatMediaLabel, mediaInputLabels as labels } from "../sessionMedia/labels";
import { useTabData } from "./TabDataContext";
import type { TabRenderContext } from "./registry";

export default function MediaInputTab({ ctx }: { ctx: TabRenderContext }): ReactElement {
  const active = ctx.activeTab === "media";
  const { page, offset, loading, error, stale, pendingIds, itemErrors, refresh, setOffset, setEnabled } =
    useTabData().media;
  const [selectedMediaId, setSelectedMediaId] = useState<string | null>(null);
  const anchor = useRef<HTMLButtonElement | null>(null);
  const refreshButton = useRef<HTMLButtonElement | null>(null);
  const selectionScope = useRef({ sessionId: ctx.sessionId, offset });
  const current = useRef({ sessionId: ctx.sessionId, active, offset });
  current.current = { sessionId: ctx.sessionId, active, offset };
  const selected = active && selectionScope.current.sessionId === ctx.sessionId && selectionScope.current.offset === offset
    ? page?.items.find((item) => item.media_id === selectedMediaId) ?? null : null;

  const closeDetails = useCallback(() => {
    setSelectedMediaId(null);
    const previous = anchor.current;
    anchor.current = null;
    if (!current.current.active || current.current.sessionId !== selectionScope.current.sessionId) return;
    if (current.current.offset === selectionScope.current.offset && previous?.isConnected) {
      previous.focus({ preventScroll: true });
    } else {
      refreshButton.current?.focus({ preventScroll: true });
    }
  }, []);

  useEffect(() => {
    if (selectedMediaId !== null && selected === null) closeDetails();
  }, [selectedMediaId, selected, closeDetails]);

  return <div className="session-media-tab">
    <div className="tab-panel-safe-top" aria-hidden="true" />
    {active && <div className="session-media-content">
      <header className="session-media-toolbar">
        <div>
          <h2 className="session-media-title-hint" data-tooltip={labels.shortNote}>{labels.title}</h2>
          <span>{formatMediaLabel(labels.count, { count: page?.total_count ?? 0 })}</span>
        </div>
        <button ref={refreshButton} type="button" disabled={loading || pendingIds.size > 0 || !ctx.sessionId}
          onClick={() => void refresh()}>{loading ? labels.refreshing : labels.refresh}</button>
      </header>
      {ctx.currentSessionArchived && <div className="session-media-warning" role="status">{labels.archived}</div>}
      {loading && !page && <div className="session-media-empty" role="status">{labels.loading}</div>}
      {pendingIds.size > 0 && !page && <div className="session-media-empty" role="status">{labels.waitingUpdates}</div>}
      {error && <div className="session-media-warning" role="alert">
        <p>{labels.readFailed}{page ? ` ${labels.stale}` : ""}</p>
        <details className="session-media-error-details"><summary>{labels.errorDetails}</summary><pre>{error}</pre></details>
      </div>}
      {stale && page && !error && <div className="session-media-warning" role="status">{labels.confirming}</div>}
      {page && page.total_count === 0 && <div className="session-media-empty">{labels.empty}</div>}
      <div className="session-media-grid">
        {page?.items.map((item, index) => <MediaGalleryTile key={`${ctx.sessionId}:${item.media_id}`} item={item}
          sessionId={ctx.sessionId} index={offset + index + 1} pending={pendingIds.has(item.media_id)}
          hasError={!!itemErrors[item.media_id]} onOpen={(element) => {
            anchor.current = element;
            selectionScope.current = { sessionId: ctx.sessionId, offset };
            setSelectedMediaId(item.media_id);
          }} />)}
      </div>
      <nav className="session-media-pagination" aria-label={labels.pagination}>
        <button type="button" disabled={loading || offset === 0}
          onClick={() => setOffset(Math.max(0, offset - SESSION_MEDIA.PAGE_SIZE))}>{labels.previous}</button>
        <span>{page && page.total_count > 0 ? formatMediaLabel(labels.range, {
          start: offset + 1, end: offset + page.items.length, total: page.total_count,
        }) : labels.noLoadedItems}</span>
        <button type="button" disabled={loading || !page || offset + page.limit >= page.total_count}
          onClick={() => setOffset(offset + SESSION_MEDIA.PAGE_SIZE)}>{labels.next}</button>
      </nav>
      {selected && <MediaDetailsWindow key={`${ctx.sessionId}:${selected.media_id}`} item={selected} sessionId={ctx.sessionId}
        disabled={stale || page?.editable !== true || ctx.currentSessionArchived}
        pending={pendingIds.has(selected.media_id)} error={itemErrors[selected.media_id] ?? null}
        onSetEnabled={(enabled) => void setEnabled(selected, enabled)} onClose={closeDetails} />}
    </div>}
  </div>;
}
