import { DiffEditor, loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor";
import type { OpenTab } from "../../types";
import ModalWindow from "../primitives/ModalWindow";

loader.config({ monaco });

export interface ConflictDialogProps {
  tab: OpenTab;
  onUseDisk(tabId: string): void;
  onUseLocal(tabId: string): Promise<boolean>;
  onRecreate(tabId: string): Promise<boolean>;
  onDiscardDeleted(tabId: string): void;
  onCancel(): void;
}

export default function ConflictDialog({
  tab,
  onUseDisk,
  onUseLocal,
  onRecreate,
  onDiscardDeleted,
  onCancel,
}: ConflictDialogProps) {
  const conflict = tab.conflict;
  if (!conflict) return null;

  if (conflict.kind === "deleted") {
    return (
      <ModalWindow
        className="agentspace-conflict-modal"
        title="文件已被外部删除"
        onClose={onCancel}
        closeOnEsc
        actions={(
          <>
            <button className="modal-btn modal-btn--secondary" onClick={onCancel}>取消</button>
            <button className="modal-btn modal-btn--neutral" onClick={() => onDiscardDeleted(tab.id)}>放弃并关闭</button>
            <button className="modal-btn modal-btn--primary" onClick={() => void onRecreate(tab.id)}>用本地内容重新创建</button>
          </>
        )}
      >
        <p>`{tab.path}` 已不存在。本地未保存内容仍保留在当前标签中。</p>
        <pre className="agentspace-conflict-local-preview">{tab.content}</pre>
      </ModalWindow>
    );
  }

  return (
    <ModalWindow
      className="agentspace-conflict-modal"
      title="文件内容冲突"
      onClose={onCancel}
      closeOnEsc
      actions={(
        <>
          <button className="modal-btn modal-btn--secondary" onClick={onCancel}>取消</button>
          <button className="modal-btn modal-btn--neutral" onClick={() => onUseDisk(tab.id)}>使用磁盘版本</button>
          <button className="modal-btn modal-btn--primary" onClick={() => void onUseLocal(tab.id)}>保留我的版本</button>
        </>
      )}
    >
      <p>`{tab.path}` 在编辑期间被外部修改。</p>
      <div className="agentspace-diff-labels" aria-hidden="true">
        <span>磁盘版本（左侧）</span>
        <span>我的版本（右侧）</span>
      </div>
      <div className="agentspace-diff-editor">
        <DiffEditor
          height="52vh"
          original={conflict.diskContent || ""}
          modified={tab.content}
          language={tab.language}
          theme="vs-dark"
          options={{
            readOnly: true,
            originalEditable: false,
            automaticLayout: true,
            renderSideBySide: true,
            useInlineViewWhenSpaceIsLimited: false,
            renderSideBySideInlineBreakpoint: 0,
            splitViewDefaultRatio: 0.5,
            ignoreTrimWhitespace: false,
            renderIndicators: true,
            renderOverviewRuler: true,
            minimap: { enabled: false },
          }}
        />
      </div>
    </ModalWindow>
  );
}
