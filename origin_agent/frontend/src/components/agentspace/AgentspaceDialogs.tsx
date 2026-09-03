import { useEffect, useState } from "react";
import type {
  AgentspaceDialogState,
  DangerousDecision,
  DirtyCloseDecision,
  TrashDirtyDecision,
} from "../../types";
import { baseName } from "../../utils/agentspacePath";
import ModalWindow from "../primitives/ModalWindow";

export interface AgentspaceDialogsProps {
  dialog: AgentspaceDialogState | null;
  onCancel(): void;
  onSubmitName(value: string): Promise<void>;
  onDirtyClose(decision: DirtyCloseDecision): Promise<void>;
  onTrashDirty(decision: TrashDirtyDecision): Promise<void>;
  onDangerous(decision: DangerousDecision): Promise<void>;
}

export default function AgentspaceDialogs({
  dialog,
  onCancel,
  onSubmitName,
  onDirtyClose,
  onTrashDirty,
  onDangerous,
}: AgentspaceDialogsProps) {
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setName(dialog?.kind === "rename" ? baseName(dialog.entry.path) : "");
    setSubmitting(false);
  }, [dialog]);

  if (!dialog) return null;

  const submitName = async () => {
    const value = name.trim();
    if (!value || value.includes("/") || value.includes("\\")) return;
    setSubmitting(true);
    try {
      await onSubmitName(value);
    } finally {
      setSubmitting(false);
    }
  };

  if (dialog.kind === "create-file" || dialog.kind === "create-folder" || dialog.kind === "rename") {
    const title = dialog.kind === "create-file"
      ? "新建文件"
      : dialog.kind === "create-folder"
        ? "新建文件夹"
        : "重命名";
    const parent = dialog.kind === "rename" ? dialog.entry.path : dialog.parentPath || "根目录";
    return (
      <ModalWindow
        className="agentspace-modal"
        title={title}
        onClose={onCancel}
        closeOnEsc
        actions={(
          <>
            <button className="modal-btn modal-btn--secondary" onClick={onCancel}>取消</button>
            <button className="modal-btn modal-btn--primary" disabled={submitting || !name.trim()} onClick={() => void submitName()}>
              {dialog.kind === "rename" ? "重命名" : "创建"}
            </button>
          </>
        )}
      >
        <label className="agentspace-dialog-label">
          <span>位置：{parent}</span>
          <input
            className="agentspace-dialog-input"
            value={name}
            autoFocus
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void submitName();
              if (event.key === "Escape") onCancel();
            }}
            placeholder={dialog.kind === "create-folder" ? "文件夹名称" : "文件名"}
          />
        </label>
      </ModalWindow>
    );
  }

  if (dialog.kind === "close-dirty") {
    const act = async (decision: DirtyCloseDecision) => {
      setSubmitting(true);
      try { await onDirtyClose(decision); } finally { setSubmitting(false); }
    };
    return (
      <ModalWindow
        className="agentspace-modal"
        title="保存更改？"
        actions={(
          <>
            <button className="modal-btn modal-btn--secondary" disabled={submitting} onClick={() => void act("cancel")}>取消</button>
            <button className="modal-btn modal-btn--neutral" disabled={submitting} onClick={() => void act("discard")}>不保存</button>
            <button className="modal-btn modal-btn--primary" disabled={submitting} onClick={() => void act("save")}>保存</button>
          </>
        )}
      >
        该标签包含未保存更改。关闭前请选择如何处理。
      </ModalWindow>
    );
  }

  if (dialog.kind === "trash-dirty") {
    const act = async (decision: TrashDirtyDecision) => {
      setSubmitting(true);
      try { await onTrashDirty(decision); } finally { setSubmitting(false); }
    };
    return (
      <ModalWindow
        className="agentspace-modal"
        title="路径包含未保存更改"
        actions={(
          <>
            <button className="modal-btn modal-btn--secondary" disabled={submitting} onClick={() => void act("cancel")}>取消</button>
            <button className="modal-btn modal-btn--neutral" disabled={submitting} onClick={() => void act("discard-all")}>放弃更改并移入</button>
            <button className="modal-btn modal-btn--primary" disabled={submitting} onClick={() => void act("save-all")}>全部保存后移入</button>
          </>
        )}
      >
        `{dialog.path}` 下有 {dialog.tabIds.length} 个未保存标签。移入垃圾桶前必须先处理这些更改。
      </ModalWindow>
    );
  }

  const title = dialog.kind === "empty-trash" ? "清空垃圾桶" : "永久删除";
  const description = dialog.kind === "empty-trash"
    ? `将永久删除垃圾桶中的 ${dialog.count} 个条目。此操作不可恢复。`
    : `将永久删除“${dialog.displayName}”。此操作不可恢复。`;
  const act = async (decision: DangerousDecision) => {
    setSubmitting(true);
    try { await onDangerous(decision); } finally { setSubmitting(false); }
  };
  return (
    <ModalWindow
      className="agentspace-modal"
      title={title}
      actions={(
        <>
          <button autoFocus className="modal-btn modal-btn--secondary" disabled={submitting} onClick={() => void act("cancel")}>取消</button>
          <button className="modal-btn modal-btn--danger" disabled={submitting} onClick={() => void act("confirm")}>永久删除</button>
        </>
      )}
    >
      {description}
    </ModalWindow>
  );
}
