import { ConfirmRequest } from "../types";
import { getToolTitle } from "../utils/toolLabels";

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

  const toolTitle = getToolTitle(pendingConfirm.tool);

  return (
    <div className="confirm-overlay">
      <div className="confirm-dialog">
        <div className="confirm-title">{toolTitle}</div>
        <div className="confirm-body">
          <pre className="confirm-cmd" style={{ maxHeight: "40vh", overflowY: "auto" }}>
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
        </div>
        <div className="confirm-actions">
          <button
            className="confirm-deny"
            onClick={() => onRespond("deny", denyReason, "user")}>
            拒绝
          </button>
          <button className="confirm-once" onClick={() => onRespond("allow_once")}>
            允许一次
          </button>
          <button className="confirm-always" onClick={() => onRespond("allow_always")}>
            始终允许
          </button>
        </div>
      </div>
    </div>
  );
}