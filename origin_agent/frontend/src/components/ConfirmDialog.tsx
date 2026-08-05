import { ConfirmRequest } from "../types";
import { getToolTitle } from "../utils/toolLabels";
import ModalWindow from "./primitives/ModalWindow";

interface ConfirmDialogProps {
  pendingConfirm: ConfirmRequest | null;
  denyReason: string;
  setDenyReason: (v: string) => void;
  onRespond: (action: string, denyReasonText?: string, deniedBy?: string) => void;
}

export default function ConfirmDialog({
  pendingConfirm,
  denyReason,
  setDenyReason,
  onRespond,
}: ConfirmDialogProps) {
  if (!pendingConfirm) return null;

  const emoji = pendingConfirm.emoji ?? "⚡";
  const toolTitle = getToolTitle(pendingConfirm.tool);
  const isCritical = pendingConfirm.danger_level === "critical";

  return (
    <ModalWindow
      title={`${emoji} ${toolTitle}`}
      actions={
        <>
          <button
            className="modal-btn modal-btn--secondary"
            onClick={() => onRespond("deny", denyReason, "user")}>
            拒绝
          </button>
          <button className="modal-btn modal-btn--neutral" onClick={() => onRespond("allow_once")}>
            允许一次
          </button>
          {!isCritical && (
            <button className="modal-btn modal-btn--primary" onClick={() => onRespond("allow_always")}>
              始终允许
            </button>
          )}
        </>
      }
    >
      <pre className="confirm-cmd">
        {Array.isArray(pendingConfirm.command)
          ? pendingConfirm.command.join(" ")
          : (pendingConfirm.command ?? pendingConfirm.content)}
      </pre>
      {pendingConfirm.reason && (
        <div className="confirm-reason">原因: {pendingConfirm.reason}</div>
      )}
      <textarea
        className="confirm-deny-reason"
        value={denyReason}
        onChange={(e) => setDenyReason(e.target.value)}
        placeholder="输入拒绝原因..."
        rows={2}
      />
    </ModalWindow>
  );
}