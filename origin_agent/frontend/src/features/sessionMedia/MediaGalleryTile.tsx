import type { ReactElement } from "react";
import { formatMediaLabel, mediaInputLabels as labels } from "./labels";
import MediaPreview from "./MediaPreview";
import type { MediaGalleryTileProps } from "./types";

export default function MediaGalleryTile({
  item, sessionId, index, pending, hasError, onOpen,
}: MediaGalleryTileProps): ReactElement {
  const path = item.source_path?.replace(/^[^:]+:/, "");
  const name = path?.split(/[\\/]/).pop()
    || formatMediaLabel(labels.unnamed, { type: labels.mediaTypes[item.media_type], index });
  const status = pending ? labels.saving : hasError ? labels.needsAttention : item.send_multimodal ? labels.enabled : labels.disabled;
  return <button type="button" className={`session-media-tile${item.send_multimodal ? "" : " is-disabled"}`}
    aria-label={formatMediaLabel(labels.openDetails, { name })} onClick={(event) => onOpen(event.currentTarget)}>
    <span className="session-media-tile-image">
      <MediaPreview key={`${sessionId}:${item.media_id}`} item={item} sessionId={sessionId} variant="thumbnail" />
      <span className="session-media-type-badge">{labels.mediaTypes[item.media_type]}</span>
      <span className={`session-media-send-badge${hasError ? " has-error" : ""}`}>{status}</span>
    </span>
    <span className="session-media-tile-name" title={item.source_path ?? name}>{name}</span>
  </button>;
}
