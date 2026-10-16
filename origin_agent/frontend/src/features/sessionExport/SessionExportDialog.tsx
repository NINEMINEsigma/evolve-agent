import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import ModalWindow from "../../components/primitives/ModalWindow";
import NoticeBanner from "../../components/primitives/NoticeBanner";
import type { SessionExportController } from "./useSessionExport";
import { exportLabels } from "./labels";

export default function SessionExportDialog({ controller }: { controller: SessionExportController }) {
  const boundary = useRef<HTMLDivElement>(null);
  const close = useRef(controller.close);
  close.current = controller.close;
  useEffect(() => {
    const previous = document.activeElement;
    const root = boundary.current;
    const first = root?.querySelector<HTMLButtonElement>("button");
    first?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close.current(); }
      if (event.key !== "Tab" || !root) return;
      const focusable = Array.from(root.querySelectorAll<HTMLElement>("button:not(:disabled),a[href],input:not(:disabled),[tabindex='0']"));
      if (!focusable.length) { event.preventDefault(); return; }
      const current = focusable.indexOf(document.activeElement as HTMLElement);
      if (event.shiftKey && current <= 0) { event.preventDefault(); focusable[focusable.length - 1].focus(); }
      else if (!event.shiftKey && (current < 0 || current === focusable.length - 1)) { event.preventDefault(); focusable[0].focus(); }
    };
    document.addEventListener("keydown", keydown, true);
    return () => {
      document.removeEventListener("keydown", keydown, true);
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, []);
  const { progress, phase, error } = controller;
  return createPortal(
    <div ref={boundary}>
      <ModalWindow title={exportLabels.title} className="session-export-dialog" actions={
        <>
          <button type="button" onClick={controller.close}>{controller.busy ? exportLabels.cancel : exportLabels.close}</button>
          {!controller.busy && phase !== "succeeded" && <button type="button" onClick={() => void controller.start()}>{exportLabels.start}</button>}
        </>
      }>
        <p>{exportLabels.scope}</p>
        <p className="session-export-warning">{exportLabels.privacy}</p>
        <p>{exportLabels.limitations}</p>
        <p>{exportLabels.offline}</p>
        <div role="status" aria-live="polite">{exportLabels[phase]}</div>
        {progress.total > 0 && (
          <div className="session-export-progress">
            <progress max={Math.max(1, progress.total)} value={progress.completed} />
            <span>{progress.completed} / {progress.total} · {(progress.bytes / 1024 / 1024).toFixed(1)} MiB · {exportLabels.issues}: {progress.issues}</span>
          </div>
        )}
        <NoticeBanner notice={error ? { kind: "error", message: error } : null} onDismiss={controller.close} />
      </ModalWindow>
    </div>, document.body,
  );
}
