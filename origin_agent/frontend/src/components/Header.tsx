interface HeaderProps {
  status: string;
  sessionId: string;
  tokenUsage: number;
  contextTokens: number;
  llmMaxContextTokens: number;
  handsfreeMode: boolean;
  approvalModelAvailable: boolean;
  approvalModelName: string;
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
  onToggleHandsfree: (enabled: boolean) => void;
}

export default function Header({
  status,
  sessionId,
  tokenUsage,
  contextTokens,
  llmMaxContextTokens,
  handsfreeMode,
  approvalModelAvailable,
  approvalModelName,
  sidebarCollapsed,
  onToggleSidebar,
  onToggleHandsfree,
}: HeaderProps) {
  return (
    <header className="app-header">
      <div className="header-left">
        <button
          className="sidebar-toggle"
          onClick={onToggleSidebar}
          title={sidebarCollapsed ? "展开侧栏" : "收起侧栏"}
        >
          {sidebarCollapsed ? (
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M9 18l6-6-6-6" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M15 18l-6-6 6-6" />
            </svg>
          )}
        </button>
        <div className="model-icon">⚡</div>
        <div>
          <div className="model-name">Evolve Agent</div>
          <div className={`model-status ${status === "已连接" ? "connected" : ""}`}>
            <span className="status-dot" />
            {status}
          </div>
        </div>
      </div>
      {sessionId && (
        <div className="header-right">
          {approvalModelAvailable && (
            <label className="handsfree-toggle" title={handsfreeMode ? "脱手模式已开启 — 工具调用由 AI 自动审批" : "脱手模式已关闭 — 工具调用需用户审批"}>
              <span className="handsfree-label">脱手</span>
              <input
                type="checkbox"
                checked={handsfreeMode}
                onChange={(e) => onToggleHandsfree(e.target.checked)}
              />
              <span className="handsfree-slider" />
            </label>
          )}
          {handsfreeMode && approvalModelName && (
            <span className="approval-model-badge" title={`审批模型: ${approvalModelName}`}>
              {approvalModelName}
            </span>
          )}
          <span className="session-badge" title="刷新页面后自动恢复此会话">
            {sessionId}
          </span>
          <span className="token-badge" title={`累计消耗: ${tokenUsage.toLocaleString()}  |  已用上下文: ${contextTokens.toLocaleString()}  |  最大上下文: ${llmMaxContextTokens > 0 ? llmMaxContextTokens.toLocaleString() : "?"}`}>
            累计 {tokenUsage.toLocaleString()} / 上下文 {contextTokens.toLocaleString()} / 上限 {llmMaxContextTokens > 0 ? llmMaxContextTokens.toLocaleString() : "?"}
          </span>
        </div>
      )}
    </header>
  );
}