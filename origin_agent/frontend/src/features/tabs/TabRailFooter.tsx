import type { ReactNode } from "react";
import type { ApprovalMode, ApprovalModeSyncStatus } from "../../types";
import ApprovalModeBadge from "../../components/ApprovalModeBadge";

export interface TabRailFooterProps {
  hasSession: boolean;
  approvalMode: ApprovalMode;
  approvalModeSyncStatus: ApprovalModeSyncStatus;
  approvalModelAvailable: boolean;
  approvalModelName: string;
  onSetApprovalMode: (mode: ApprovalMode) => void;
  commandMenu: ReactNode;
}

export default function TabRailFooter({
  hasSession,
  approvalMode,
  approvalModeSyncStatus,
  approvalModelAvailable,
  approvalModelName,
  onSetApprovalMode,
  commandMenu,
}: TabRailFooterProps) {
  return (
    <div className="tab-rail-footer" data-tour="tab-rail-footer">
      {hasSession ? (
        <ApprovalModeBadge
          mode={approvalMode}
          syncStatus={approvalModeSyncStatus}
          approvalModelAvailable={approvalModelAvailable}
          approvalModelName={approvalModelName}
          onSetApprovalMode={onSetApprovalMode}
        />
      ) : (
        <button
          type="button"
          className="approval-model-badge sync-unavailable tab-rail-footer-button"
          disabled
          data-tooltip="当前没有会话，无法切换审批模式"
          aria-label="当前没有会话，无法切换审批模式"
        >
          不可用
        </button>
      )}
      {commandMenu}
    </div>
  );
}
