import { SessionInfo } from "../types";
import { formatTime } from "../utils";

interface SidebarProps {
  collapsed?: boolean;
  sessions: SessionInfo[];
  sessionId: string;
  searchQuery: string;
  setSearchQuery: (q: string) => void;
  mergeMode: boolean;
  selectedForMerge: Set<string>;
  onToggleMergeMode: () => void;
  onToggleMergeSelect: (sid: string) => void;
  onNewChat: () => void;
  onSwitchSession: (sid: string) => void;
  onContextMenu: (e: React.MouseEvent, sid: string) => void;
  onMergeSessions: (sources: string[]) => void;
  sidebarSessions: SessionInfo[];
}

function sessionLabel(s: SessionInfo) {
  return s.title || s.id.slice(0, 8) + "...";
}

function buildTooltip(s: SessionInfo): string {
  const parts: string[] = [];
  parts.push(`ID: ${s.id}`);
  parts.push(`时间: ${formatTime(s.last_activity_at || s.created_at)}`);
  if (s.status === "archived") parts.push("状态: 已归档");
  if (s.tags?.length) parts.push(`标签: ${s.tags.join(", ")}`);
  return parts.join("\n");
}

function RelatedSessionShortcut({
  session,
  kind,
  onSwitchSession,
}: {
  session: SessionInfo;
  kind: "parent" | "continuation";
  onSwitchSession: (sid: string) => void;
}) {
  const isParent = kind === "parent";
  return (
    <button
      className={`relation-shortcut ${isParent ? "relation-shortcut-parent" : "relation-shortcut-continuation"}`}
      data-tooltip={isParent ? "当前会话继承自此会话" : "继承自当前会话"}
      onClick={(e) => {
        e.stopPropagation();
        onSwitchSession(session.id);
      }}
    >
      <span className="relation-shortcut-title">{sessionLabel(session)}</span>
    </button>
  );
}

function SessionListItem({
  session: s,
  sessionId,
  sessions,
  mergeMode,
  selectedForMerge,
  onToggleMergeSelect,
  onSwitchSession,
  onContextMenu,
}: {
  session: SessionInfo;
  sessionId: string;
  sessions: SessionInfo[];
  mergeMode: boolean;
  selectedForMerge: Set<string>;
  onToggleMergeSelect: (sid: string) => void;
  onSwitchSession: (sid: string) => void;
  onContextMenu: (e: React.MouseEvent, sid: string) => void;
}) {
  const isArchived = s.status === "archived";
  const canSelectForMerge = mergeMode && isArchived;
  const current = sessions.find((cs) => cs.id === sessionId);
  const isParentOfCurrent = current?.parents?.includes(s.id) ?? false;
  const isContinuationOfCurrent = current?.continuation === s.id;
  const relationTooltip = isParentOfCurrent
    ? "当前会话继承自此会话"
    : isContinuationOfCurrent
      ? "继承自当前会话"
      : undefined;

  return (
    <div
      data-tooltip={relationTooltip || buildTooltip(s)}
      className={`session-item ${s.id === sessionId ? "active" : ""} ${isArchived ? "archived" : ""} ${isParentOfCurrent ? "parent-session" : ""} ${isContinuationOfCurrent ? "continuation-session" : ""} ${mergeMode && !isArchived ? "merge-unavailable" : ""}`}
      onClick={() => {
        if (canSelectForMerge) onToggleMergeSelect(s.id);
        else if (!mergeMode) onSwitchSession(s.id);
      }}
      onContextMenu={(e) => {
        if (!mergeMode) onContextMenu(e, s.id);
      }}
    >
      {mergeMode && (
        isArchived ? (
          <input
            type="checkbox"
            checked={selectedForMerge.has(s.id)}
            onChange={() => onToggleMergeSelect(s.id)}
            onClick={(e) => e.stopPropagation()}
            className="merge-checkbox"
          />
        ) : (
          <span className="merge-placeholder" data-tooltip="未归档会话不可合并">—</span>
        )
      )}
      <span className="session-item-title">
        {s.pinned && <span className="pinned-mark" data-tooltip="已收藏">★</span>}
        {sessionLabel(s)}
      </span>
      {!mergeMode && (
        <button
          className="session-item-more"
          onClick={(e) => {
            e.stopPropagation();
            onContextMenu(e, s.id);
          }}
          data-tooltip="更多操作"
        >
          ⋮
        </button>
      )}
    </div>
  );
}

export default function Sidebar({
  collapsed,
  sessions,
  sessionId,
  searchQuery,
  setSearchQuery,
  mergeMode,
  selectedForMerge,
  onToggleMergeMode,
  onToggleMergeSelect,
  onNewChat,
  onSwitchSession,
  onContextMenu,
  onMergeSessions,
  sidebarSessions,
}: SidebarProps) {
  const currentSession = sessions.find((s) => s.id === sessionId);
  const parentSessions = currentSession?.parents
    ?.map((pid) => sessions.find((s) => s.id === pid))
    .filter((s): s is SessionInfo => Boolean(s)) ?? [];
  const continuationSession = currentSession?.continuation
    ? sessions.find((s) => s.id === currentSession.continuation)
    : undefined;
  return (
    <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
      <div className="sidebar-header">
        <div className="sidebar-toolbar">
          <div className="sidebar-search">
            <textarea
              className="search-input"
              rows={1}
              placeholder="Search chats..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) e.preventDefault();
              }}
            />
          </div>
          <button
            className={`icon-btn ${mergeMode ? 'active' : ''}`}
            onClick={onToggleMergeMode}
            data-tooltip={mergeMode ? '退出多选' : '多选合并'}
            aria-label={mergeMode ? '退出多选' : '多选合并'}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="5" cy="12" r="1.6" />
              <circle cx="12" cy="12" r="1.6" />
              <circle cx="19" cy="12" r="1.6" />
            </svg>
          </button>
          <button
            className="icon-btn"
            onClick={onNewChat}
            data-tooltip="新建会话"
            aria-label="新建会话"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 20h9" />
              <path d="M16.5 3.5a2.121 2.121 0 1 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
            </svg>
          </button>
        </div>
      </div>
      <div className="session-list">
        {sidebarSessions.length === 0 ? (
          <div className="session-empty">无匹配会话</div>
        ) : (
          sidebarSessions.map((s) => (
            <div key={s.id}>
              <SessionListItem
                session={s}
                sessionId={sessionId}
                sessions={sessions}
                mergeMode={mergeMode}
                selectedForMerge={selectedForMerge}
                onToggleMergeSelect={onToggleMergeSelect}
                onSwitchSession={onSwitchSession}
                onContextMenu={onContextMenu}
              />
              {s.id === sessionId && (parentSessions.length > 0 || continuationSession) && (
                <div className="relation-shortcuts relation-shortcuts">
                  {parentSessions.map((parent) => (
                    <RelatedSessionShortcut
                      key={parent.id}
                      session={parent}
                      kind="parent"
                      onSwitchSession={onSwitchSession}
                    />
                  ))}
                  {continuationSession && (
                    <RelatedSessionShortcut
                      session={continuationSession}
                      kind="continuation"
                      onSwitchSession={onSwitchSession}
                    />
                  )}
                </div>
              )}
            </div>
          ))
        )}
      </div>
      {mergeMode && selectedForMerge.size >= 2 && (
        <div className="merge-bar">
          <span>已选 {selectedForMerge.size} 个会话</span>
          <button onClick={() => { onMergeSessions(Array.from(selectedForMerge)); }}>
            合并延续
          </button>
        </div>
      )}
    </aside>
  );
}