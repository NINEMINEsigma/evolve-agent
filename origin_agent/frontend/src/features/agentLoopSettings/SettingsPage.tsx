import { useEffect, useId } from "react";
import { agentLoopSettingsLabels as labels } from "./labels";
import { useAgentLoopSettings } from "./useAgentLoopSettings";

export default function AgentLoopSettingsPage({ active }: { active: boolean }) {
  const editor = useAgentLoopSettings(active);
  const id = useId();
  const editable = editor.readStatus === "ready" && !editor.loading && !editor.busy
    && editor.saveOutcome !== "uncertain" && editor.state !== null;
  const requestPending = editor.loading || editor.busy;
  const uncertain = editor.saveOutcome === "uncertain";

  useEffect(() => {
    if (!editor.shouldBlockUnload) return;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [editor.shouldBlockUnload]);

  return (
    <div className="agent-loop-settings-page">
      <section className="llm-reference-card" aria-labelledby={`${id}-title`}>
        <div className="llm-reference-title">
          <h3 id={`${id}-title`}>{labels.title}</h3>
        </div>
        <form onSubmit={(event) => { event.preventDefault(); void editor.save(); }}>
          <div className="llm-field">
            <input id={`${id}-limit`} type="text" inputMode="numeric" autoComplete="off"
              value={editor.draft} disabled={!editable}
              aria-labelledby={`${id}-title`} aria-invalid={!!editor.validationError}
              aria-describedby={editor.validationError ? `${id}-validation` : undefined}
              onChange={(event) => editor.setDraft(event.target.value)} />
          </div>
          {editor.validationError && <p id={`${id}-validation`} className="llm-field-error" role="alert">
            {editor.validationError}
          </p>}
          <div className="llm-inline-actions">
            <button type="submit" className="llm-button llm-button--primary" disabled={!editable || !editor.dirty}>
              {editor.busy ? labels.saving : labels.save}
            </button>
            <button type="button" className="llm-button" disabled={!editable}
              onClick={() => void editor.restoreDefault()}>{labels.restoreDefault}</button>
          </div>
        </form>
        <div className="agent-loop-settings-status" role="status" aria-live="polite">
          {editor.loading && <p>{labels.loading}</p>}
          {editor.busy && <p>{labels.saving}</p>}
          {uncertain && !editor.error && <p>{labels.unknownSave}</p>}
          {editor.dirty && <p>{labels.dirty}</p>}
          {editor.externalChange && <p>{labels.externalChange}</p>}
          {editor.notice && <p>{editor.notice}</p>}
        </div>
        {editor.error && <div className="llm-message llm-message--error" role="alert">
          <p>{uncertain ? labels.unknownSave : editor.readStatus === "error" ? labels.readFailed : labels.saveFailed}</p>
          <button type="button" className="llm-text-button" disabled={requestPending}
            onClick={() => void editor.refresh()}>{labels.retry}</button>
          <details><summary>{labels.errorDetails}</summary><p>{editor.error}</p></details>
        </div>}
      </section>
    </div>
  );
}
