import { useState, useRef, useEffect, useLayoutEffect, useCallback, useMemo } from "react";
import { SubagentSession } from "../types";
import MessageItem from "./MessageItem";
import Minimap from "./Minimap";
import { subagentFeedbackToChatMessages } from "../utils";

interface SubagentDrawerProps {
  open: boolean;
  onClose: () => void;
  subagentSessions: Record<string, SubagentSession>;
}

const STATUS_LABEL: Record<SubagentSession["status"], string> = {
  running: "运行中",
  waiting: "等待",
  completed: "已完成",
  terminated: "已终止",
};

export default function SubagentDrawer({
  open,
  onClose,
  subagentSessions,
}: SubagentDrawerProps) {
  const [collapsedSessions, setCollapsedSessions] = useState<Set<string>>(new Set());
  const [openTick, setOpenTick] = useState(0);

  useEffect(() => {
    if (open) setOpenTick((t) => t + 1);
  }, [open]);

  if (!open) return null;

  const items = Object.values(subagentSessions);

  const toggleCollapse = (sid: string) => {
    setCollapsedSessions((prev) => {
      const next = new Set(prev);
      next.has(sid) ? next.delete(sid) : next.add(sid);
      return next;
    });
  };

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer-panel subagent-drawer" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-header">
          <span className="drawer-title">子会话 ({items.length})</span>
          <button className="drawer-close" onClick={onClose}>✕</button>
        </div>
        <div className="drawer-body">
          {items.length === 0 && (
            <div className="drawer-empty">暂无子会话</div>
          )}
          {items.map((session, index) => (
            <SubagentCard
              key={session.session_id}
              session={session}
              collapsed={collapsedSessions.has(session.session_id)}
              onToggleCollapse={() => toggleCollapse(session.session_id)}
              openTick={openTick + index}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

interface SubagentCardProps {
  session: SubagentSession;
  collapsed: boolean;
  onToggleCollapse: () => void;
  disableToggle?: boolean;
  openTick?: number;
}

export function SubagentCard({ session, collapsed, onToggleCollapse, disableToggle, openTick }: SubagentCardProps) {
  const chatRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [expandedMessages, setExpandedMessages] = useState<Set<string>>(new Set());
  const isInactive = session.status === "terminated" || session.status === "completed";

  const chatMessages = useMemo(() => subagentFeedbackToChatMessages(session), [session]);

  const toggleMessageCollapse = useCallback((id: string) => {
    setExpandedMessages((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const messagesWithCollapse = useMemo(() =>
    chatMessages.map((m) => ({
      ...m,
      collapsed: expandedMessages.has(m.id) ? false : true,
    })),
    [chatMessages, expandedMessages]
  );

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ block: "end", inline: "nearest", behavior: "auto" });
  }, []);

  useLayoutEffect(() => {
    if (collapsed) return;
    scrollToBottom();

    const el = chatRef.current;
    if (!el) return;

    const ro = new ResizeObserver(() => {
      scrollToBottom();
    });
    ro.observe(el);

    const timers = [
      setTimeout(scrollToBottom, 50),
      setTimeout(scrollToBottom, 150),
      setTimeout(scrollToBottom, 350),
      setTimeout(scrollToBottom, 700),
    ];

    return () => {
      ro.disconnect();
      timers.forEach(clearTimeout);
    };
  }, [collapsed, session.session_id, openTick, scrollToBottom]);

  useEffect(() => {
    if (!collapsed) {
      scrollToBottom();
    }
  }, [collapsed, chatMessages.length, scrollToBottom]);

  return (
    <div className={`subagent-card ${isInactive ? "inactive" : "active"}`}>
      <div className={`subagent-info ${disableToggle ? "no-toggle" : ""}`} onClick={disableToggle ? undefined : onToggleCollapse}>
      <span className="subagent-name">
        <span className="subagent-collapse-arrow">{collapsed ? "▶" : "▼"}</span>
        {session.name || session.session_id.slice(0, 12)}
        <span className="subagent-feedback-count">
          {session.feedback.length} 条
        </span>
      </span>
      <span className="subagent-status-container">
        <span className={`subagent-status subagent-status-${session.status}`}>
          {STATUS_LABEL[session.status] ?? session.status}
        </span>
      </span>
    </div>

    {!collapsed && (
      <div className="subagent-chat-wrapper">
        <div className="subagent-chat subagent-chat-scroll" ref={chatRef}>
          {messagesWithCollapse.length === 0 && (
            <div className="drawer-empty subagent-chat-empty">等待子会话响应...</div>
          )}
          {messagesWithCollapse.map((message) => (
            <MessageItem
              key={message.id}
              message={message}
              archived={false}
              onImageClick={() => {}}
              onToggleCollapse={toggleMessageCollapse}
              onEditMessage={() => {}}
            />
          ))}
          <div ref={bottomRef} />
        </div>
        <Minimap messages={messagesWithCollapse} chatAreaRef={chatRef} />
      </div>
    )}
  </div>
  );
}
