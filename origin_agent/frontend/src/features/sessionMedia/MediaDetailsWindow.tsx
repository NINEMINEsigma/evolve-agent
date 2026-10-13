import { useEffect, useRef } from "react";
import type { ReactElement } from "react";
import { createPortal } from "react-dom";
import ModalWindow from "../../components/primitives/ModalWindow";
import { formatMediaLabel, mediaInputLabels as labels } from "./labels";
import MediaPreview from "./MediaPreview";
import type { MediaDetailsWindowProps } from "./types";

export default function MediaDetailsWindow({
  item, sessionId, disabled, pending, error, onSetEnabled, onClose,
}: MediaDetailsWindowProps): ReactElement {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const closeButton = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    closeButton.current?.focus({ preventScroll: true });
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const container = containerRef.current;
      if (container === null) return;
      const controls = Array.from(container.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], audio[controls], video[controls], [tabindex]:not([tabindex="-1"])',
      )).filter((element) => !element.hasAttribute("disabled") && element.getClientRects().length > 0);
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (!first || !last) return;
      if (!container.contains(document.activeElement)
        || (event.shiftKey && document.activeElement === first)
        || (!event.shiftKey && document.activeElement === last)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [sessionId, item.media_id]);

  const actions = <button ref={closeButton} type="button" className="modal-btn modal-btn--secondary"
    onClick={onClose}>{labels.close}</button>;
  return createPortal(<div ref={containerRef} className="session-media-modal-root">
    <ModalWindow title={labels.detailsTitle} actions={actions} onClose={onClose}
      closeOnOverlayClick closeOnEsc className="session-media-details-window">
      <div className="session-media-details-layout">
        <section className="session-media-details-preview">
          <MediaPreview key={`${sessionId}:${item.media_id}`} item={item} sessionId={sessionId} variant="detail" />
        </section>
        <section className="session-media-details-info">
          <div className="session-media-settings">
            <label className="session-media-switch">
              <input type="checkbox" checked={item.send_multimodal} disabled={disabled || pending}
                onChange={(event) => onSetEnabled(event.target.checked)} />
              <span>{labels.sendLabel}</span>
            </label>
            <div className="session-media-setting-state" role="status">
              {pending ? labels.saving : item.send_multimodal ? labels.enabled : labels.disabled}
            </div>
            <p className="session-media-note">{labels.sendDescription}</p>
            <p className="session-media-note">{labels.forwardingNote}</p>
            <p className="session-media-note">{labels.timingNote}</p>
          </div>
          {disabled && <p className="session-media-warning" role="status">{labels.settingsDisabled}</p>}
          {error && <div className="session-media-warning" role="alert">
            <p>{error.startsWith(labels.unknownSave) ? labels.unknownSave : labels.saveFailed}</p>
            <details className="session-media-error-details"><summary>{labels.errorDetails}</summary><pre>{error}</pre></details>
          </div>}
          <dl className="session-media-details-fields">
            <dt>{labels.source}</dt><dd>{item.source_path ?? labels.unknownSource}</dd>
            <dt>{labels.character}</dt><dd>{item.character_name ?? labels.roles[item.role]}</dd>
            <dt>{labels.messageType}</dt><dd>{labels.roles[item.role]}</dd>
            <dt>{labels.historyLocation}</dt><dd>{formatMediaLabel(labels.historyLocationValue, {
              message: item.history_index + 1, block: item.block_index + 1,
            })}</dd>
            <dt>{labels.descriptionCache}</dt><dd>{item.has_forward_description ? labels.cached : labels.notCached}</dd>
            <dt>{labels.inlineSize}</dt><dd>{item.inline_payload_chars === null ? labels.remoteMedia
              : formatMediaLabel(labels.inlineSizeValue, { size: (item.inline_payload_chars / 1024).toFixed(1) })}</dd>
            {item.mime_type && <><dt>{labels.mimeType}</dt><dd><code>{item.mime_type}</code></dd></>}
            {item.tool_call_id && <><dt>{labels.toolCall}</dt><dd><code>{item.tool_call_id}</code></dd></>}
            <dt>{labels.identity}</dt><dd><code>{item.media_id}</code></dd>
          </dl>
        </section>
      </div>
    </ModalWindow>
  </div>, document.body);
}
