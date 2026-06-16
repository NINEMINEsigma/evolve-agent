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
      title={isParent ? "当前会话继承自此会话" : "继承自当前会话"}
      onClick={(e) => {
        e.stopPropagation();
        onSwitchSession(session.id);
      }}
    >
      <span className="relation-shortcut-label">{isParent ? "父会话" : "继承会话"}</span>
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
      title={relationTooltip}
      className={`session-item ${s.id === sessionId ? "active" : ""} ${isArchived ? "archived" : ""} ${isParentOfCurrent ? "parent-session" : ""} ${isContinuationOfCurrent ? "continuation-session" : ""} ${mergeMode && !isArchived ? "merge-unavailable" : ""}`}
      onClick={() => {
        if (canSelectForMerge) onToggleMergeSelect(s.id);
        else if (!mergeMode) onSwitchSession(s.id);
      }}
      onContextMenu={(e) => {
        if (!mergeMode) onContextMenu(e, s.id);
      }}
    >
      <div className="session-item-content">
        <div className="session-item-row">
          {mergeMode && (
            isArchived ? (
              <input
                type="checkbox"
                checked={selectedForMerge.has(s.id)}
                onChange={() => onToggleMergeSelect(s.id)}
                onClick={(e) => e.stopPropagation()}
              />
            ) : (
              <span className="merge-placeholder" title="未归档会话不可合并">—</span>
            )
          )}
          <div className="session-item-title">
            {isParentOfCurrent && <span className="parent-mark" />}
            {isContinuationOfCurrent && <span className="continuation-mark" />}
            {s.pinned && <span className="pin-badge">★</span>}
            {sessionLabel(s)}
            {isArchived && <span className="archived-badge">已归档</span>}
          </div>
        </div>
        <div className="session-item-sub">
          <span className="session-item-id">{s.id}</span>
          <span className="session-item-time">{formatTime(s.last_activity_at || s.created_at)}</span>
        </div>
        {(s.tags?.length || 0) > 0 && (
          <div className="session-tags">
            {s.tags!.map((t) => (
              <span key={t} className="session-tag">{t}</span>
            ))}
          </div>
        )}
      </div>
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
        <div className="sidebar-title">💬 会话</div>
        <button className="new-chat-btn" onClick={onNewChat}>+ 新对话</button>
        <div className="sidebar-search">
          <input
            className="search-input"
            type="text"
            placeholder="搜索会话..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
        <button
          className={`merge-mode-toggle ${mergeMode ? 'active' : ''}`}
          onClick={onToggleMergeMode}
        >
          {mergeMode ? '退出多选' : '多选合并'}
        </button>
      </div>
      <div className="session-list">
        {sidebarSessions.length === 0 ? (
          <div className="session-empty">无匹配会话</div>
        ) : (
          sidebarSessions.map((s) => (
            <div key={s.id}>
              {s.id === sessionId && (parentSessions.length > 0 || continuationSession) && (
                <div className="relation-shortcuts relation-shortcuts-before">
                  {parentSessions.map((parent) => (
                    <RelatedSessionShortcut
                      key={parent.id}
                      session={parent}
                      kind="parent"
                      onSwitchSession={onSwitchSession}
                    />
                  ))}
                </div>
              )}
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
              {s.id === sessionId && continuationSession && (
                <div className="relation-shortcuts relation-shortcuts-after">
                  <RelatedSessionShortcut
                    session={continuationSession}
                    kind="continuation"
                    onSwitchSession={onSwitchSession}
                  />
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