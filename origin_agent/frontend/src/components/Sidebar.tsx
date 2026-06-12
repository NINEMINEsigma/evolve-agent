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
  const current = sessions.find((cs) => cs.id === sessionId);
  const isParentOfCurrent = current?.parents?.includes(s.id) ?? false;

  return (
    <div
      className={`session-item ${s.id === sessionId ? "active" : ""} ${isArchived ? "archived" : ""} ${isParentOfCurrent ? "parent-session" : ""}`}
      onClick={() => {
        if (mergeMode) onToggleMergeSelect(s.id);
        else onSwitchSession(s.id);
      }}
      onContextMenu={(e) => {
        if (!mergeMode) onContextMenu(e, s.id);
      }}
    >
      <div className="session-item-content">
        <div className="session-item-row">
          {mergeMode && (
            <input
              type="checkbox"
              checked={selectedForMerge.has(s.id)}
              onChange={() => onToggleMergeSelect(s.id)}
              onClick={(e) => e.stopPropagation()}
            />
          )}
          <div className="session-item-title">
            {isParentOfCurrent && <span className="parent-mark" />}
            {s.pinned && <span className="pin-badge">★</span>}
            {s.title || s.id.slice(0, 8) + "..."}
            {isArchived && <span className="archived-badge">已归档</span>}
          </div>
        </div>
        <div className="session-item-sub">
          <span className="session-item-id">{s.id}</span>
          <span className="session-item-time">{formatTime(s.last_activity_at || s.created_at)}</span>
        </div>
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
            <SessionListItem
              key={s.id}
              session={s}
              sessionId={sessionId}
              sessions={sessions}
              mergeMode={mergeMode}
              selectedForMerge={selectedForMerge}
              onToggleMergeSelect={onToggleMergeSelect}
              onSwitchSession={onSwitchSession}
              onContextMenu={onContextMenu}
            />
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