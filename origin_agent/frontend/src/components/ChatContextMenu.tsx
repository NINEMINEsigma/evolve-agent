import { useRef, useEffect } from "react";
import { SessionInfo } from "../types";

interface ChatContextMenuProps {
  contextMenu: { x: number; y: number; sid: string } | null;
  onClose: () => void;
  sessions: SessionInfo[];
  generatingTitleSessions: Set<string>;
  generatingTagSessions: Set<string>;
  terminatingSessions: Set<string>;
  onAutoTitle: (sid: string) => void;
  onAutoTag: (sid: string) => void;
  onTogglePin: (sid: string) => void;
  onEditTags: (sid: string) => void;
  onBranch: (sid: string) => void;
  onTerminate: (sid: string) => void;
  onDelete: (sid: string) => void;
  onRegenerateSummary: (sid: string) => void;
}

export default function ChatContextMenu({
  contextMenu,
  onClose,
  sessions,
  generatingTitleSessions,
  generatingTagSessions,
  terminatingSessions,
  onAutoTitle,
  onAutoTag,
  onTogglePin,
  onEditTags,
  onBranch,
  onTerminate,
  onDelete,
  onRegenerateSummary,
}: ChatContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    const escHandler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    if (contextMenu) {
      document.addEventListener("mousedown", handler);
      document.addEventListener("keydown", escHandler);
    }
    return () => {
      document.removeEventListener("mousedown", handler);
      document.removeEventListener("keydown", escHandler);
    };
  }, [contextMenu, onClose]);

  if (!contextMenu) return null;

  const session = sessions.find((s) => s.id === contextMenu.sid);

  return (
    <div
      ref={menuRef}
      className="context-menu"
      style={{ left: contextMenu.x, top: contextMenu.y }}
    >
      <ContextMenuItem
        disabled={generatingTitleSessions.has(contextMenu.sid)}
        onClick={() => { onClose(); onAutoTitle(contextMenu.sid); }}
        label={generatingTitleSessions.has(contextMenu.sid) ? "⏳ 命名中..." : "自动命名"}
      />
      <ContextMenuItem
        disabled={generatingTagSessions.has(contextMenu.sid)}
        onClick={() => { onClose(); onAutoTag(contextMenu.sid); }}
        label={generatingTagSessions.has(contextMenu.sid) ? "⏳ 生成标签中..." : "自动标签"}
      />
      <ContextMenuItem
        onClick={() => { onClose(); onTogglePin(contextMenu.sid); }}
        label={session?.pinned ? "取消收藏" : "收藏"}
      />
      <ContextMenuItem
        onClick={() => { onClose(); onEditTags(contextMenu.sid); }}
        label="编辑标签"
      />
      <SessionLifecycleItem
        session={session}
        sid={contextMenu.sid}
        terminating={terminatingSessions.has(contextMenu.sid)}
        generatingTitle={generatingTitleSessions.has(contextMenu.sid)}
        onClose={onClose}
        onBranch={onBranch}
        onTerminate={onTerminate}
        onRegenerateSummary={onRegenerateSummary}
      />
      <div className="context-menu-separator" />
      <ContextMenuItem
        danger
        onClick={() => { onClose(); onDelete(contextMenu.sid); }}
        label="删除会话"
      />
    </div>
  );
}

function ContextMenuItem({
  label,
  onClick,
  disabled,
  danger,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
}) {
  return (
    <div
      className={`context-menu-item ${disabled ? "context-menu-item-disabled" : ""} ${danger ? "context-menu-item-danger" : ""}`}
      onClick={() => { if (!disabled) onClick(); }}
    >
      {label}
    </div>
  );
}

function SessionLifecycleItem({
  session,
  sid,
  terminating,
  generatingTitle,
  onClose,
  onBranch,
  onTerminate,
  onRegenerateSummary,
}: {
  session?: SessionInfo;
  sid: string;
  terminating: boolean;
  generatingTitle: boolean;
  onClose: () => void;
  onBranch: (sid: string) => void;
  onTerminate: (sid: string) => void;
  onRegenerateSummary: (sid: string) => void;
}) {
  if (!session) return null;
  if (session.status === "archived") {
    return (
      <>
        <ContextMenuItem
          onClick={() => { onClose(); onBranch(sid); }}
          label="继续此会话"
        />
        <ContextMenuItem
          disabled={generatingTitle}
          onClick={() => { if (!generatingTitle) { onClose(); onRegenerateSummary(sid); } }}
          label={generatingTitle ? "⏳ 生成摘要中..." : "重新生成摘要"}
        />
      </>
    );
  }
  return (
    <ContextMenuItem
      disabled={terminating}
      onClick={() => { if (!terminating) { onClose(); onTerminate(sid); } }}
      label={terminating ? "⏳ 终结中..." : "终结"}
    />
  );
}