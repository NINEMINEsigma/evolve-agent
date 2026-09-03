import type { CursorPosition, OpenTab, SyncState } from "../../types";

export interface StatusBarProps {
  activeTab: OpenTab | null;
  cursor: CursorPosition | null;
  syncState: SyncState;
}

export default function StatusBar({ activeTab, cursor, syncState }: StatusBarProps) {
  const syncLabel = syncState === "live"
    ? "实时同步"
    : syncState === "connecting"
      ? "正在连接同步"
      : "实时同步不可用";
  return (
    <div className={`agentspace-status-bar agentspace-sync-${syncState}`}>
      <div className="agentspace-status-left">
        {activeTab ? (
          <>
            <span className="agentspace-status-item" title={activeTab.path}>{activeTab.path}</span>
            <span className="agentspace-status-item">{activeTab.language}</span>
            <span className="agentspace-status-item">UTF-8</span>
            {cursor && <span className="agentspace-status-item">行 {cursor.line}，列 {cursor.column}</span>}
          </>
        ) : (
          <span className="agentspace-status-item">未打开文件</span>
        )}
      </div>
      <div className="agentspace-status-right">
        {activeTab?.isDirty && <span className="agentspace-status-item">未保存</span>}
        {activeTab?.conflict && <span className="agentspace-status-item agentspace-status-conflict">存在冲突</span>}
        {activeTab?.isLocked && (
          <span className="agentspace-status-item agentspace-status-locked">
            {activeTab.lockOwners.map((owner) => owner.character_name).filter(Boolean).join("、") || "Agent"} 使用中
          </span>
        )}
        <span className="agentspace-status-item">{syncLabel}</span>
      </div>
    </div>
  );
}
