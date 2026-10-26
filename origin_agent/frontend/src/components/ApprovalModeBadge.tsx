import type { ApprovalMode, ApprovalModeSyncStatus } from "../types";

export interface ApprovalModeBadgeProps {
  mode: ApprovalMode;
  syncStatus: ApprovalModeSyncStatus;
  approvalModelAvailable: boolean;
  approvalModelName: string;
  onSetApprovalMode: (mode: ApprovalMode) => void;
  className?: string;
}

export default function ApprovalModeBadge({
  mode,
  syncStatus,
  approvalModelAvailable,
  approvalModelName,
  onSetApprovalMode,
  className = "",
}: ApprovalModeBadgeProps) {
  const disabled = syncStatus !== "ready";
  const label = syncStatus === "loading"
    ? "加载中"
    : syncStatus === "unavailable"
      ? "不可用"
      : mode === "yolo"
        ? "YOLO"
        : mode === "handsfree"
          ? approvalModelName || "自动审批"
          : "手动";
  const tooltip = syncStatus === "loading"
    ? "正在同步当前会话的审批模式"
    : syncStatus === "unavailable"
      ? "连接不可用，无法确认当前会话的审批模式"
      : mode === "yolo"
        ? "YOLO 模式 — 所有工具调用自动批准（含 critical）"
        : mode === "handsfree"
          ? approvalModelAvailable
            ? "脱手模式 — 工具调用由 AI 自动审批"
            : "当前审批 Profile 不可用，无法执行脱手模式审批"
          : approvalModelAvailable
            ? "手动模式 — 工具调用需用户审批"
            : "手动模式 — 未配置可用审批 Profile，下一次切换将进入 YOLO 模式";
  const stateClass = syncStatus === "ready"
    ? mode !== "manual" ? "handsfree-on" : "handsfree-off"
    : syncStatus === "loading" ? "sync-loading" : "sync-unavailable";

  const cycleMode = () => {
    if (mode === "manual") onSetApprovalMode(approvalModelAvailable ? "handsfree" : "yolo");
    else if (mode === "handsfree") onSetApprovalMode("yolo");
    else onSetApprovalMode("manual");
  };

  return (
    <button
      type="button"
      className={`approval-mode-badge ${stateClass} ${className}`}
      data-approval-mode={mode}
      data-tooltip={tooltip}
      onClick={cycleMode}
      disabled={disabled}
      aria-label={`审批模式：${label}`}
    >
      <span className="approval-mode-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round">
          <path d="M12 3 19 6v5c0 4.7-2.9 8.1-7 10-4.1-1.9-7-5.3-7-10V6l7-3Z" />
          <path d="m9.5 12 1.7 1.7 3.5-3.5" />
        </svg>
      </span>
      <span className="approval-mode-label">{label}</span>
      <span className="approval-mode-caret" aria-hidden="true">⌄</span>
    </button>
  );
}
