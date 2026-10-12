import { useState, useRef, useEffect, useLayoutEffect, useCallback, useMemo } from "react";
import { SubagentSession } from "../types";
import MessageItem from "./MessageItem";
import RoundNavRail from "./RoundNavRail";
import { subagentFeedbackToChatMessages } from "../utils";
import { SID_DISPLAY_LEN } from "../constants/session";
import { ROUND_NAV_JUMP_OFFSET_RATIO } from "../constants/roundNav";
import { useChatRuntimeStore } from "../features/chat/chatRuntimeStore";
import { isMessageVisible } from "../features/chat/messageVisibility";
import { buildRoundNavEntriesFromMessages, type RoundNavEntry } from "../features/chat/roundNav";
import SubagentAvatar from "../features/characterAvatars/SubagentAvatar";

const STATUS_LABEL: Record<SubagentSession["status"], string> = {
  running: "运行中",
  completed: "已完成",
  terminated: "已终止",
};

interface SubagentCardProps {
  session: SubagentSession;
  collapsed: boolean;
  onToggleCollapse: () => void;
  disableToggle?: boolean;
}

export function SubagentCard({ session, collapsed, onToggleCollapse, disableToggle }: SubagentCardProps) {
  const chatRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [expandedMessages, setExpandedMessages] = useState<Set<string>>(new Set());
  const isInactive = session.status === "terminated" || session.status === "completed";

  const showSystemUserMessages = useChatRuntimeStore((state) => state.showSystemUserMessages);
  const chatMessages = useMemo(() => subagentFeedbackToChatMessages(session)
    .filter((message) => isMessageVisible(message.role, message.characterName, showSystemUserMessages)),
  [session, showSystemUserMessages]);

  const roundNavEntries = useMemo(() => buildRoundNavEntriesFromMessages(chatMessages), [chatMessages]);
  const [currentRoundEntryId, setCurrentRoundEntryId] = useState<string | null>(null);
  const roundNavFrameRef = useRef<number | null>(null);

  // 当前轮：视口参考线（顶部 + 35% 高度）以上最近的 user 消息
  useEffect(() => {
    const chat = chatRef.current;
    if (!chat || collapsed) return;
    const update = () => {
      roundNavFrameRef.current = null;
      const reference = chat.scrollTop + chat.clientHeight * ROUND_NAV_JUMP_OFFSET_RATIO;
      let current: string | null = null;
      for (const entry of roundNavEntries) {
        const element = chat.querySelector<HTMLElement>(`[data-message-id="${entry.entryId}"]`);
        if (!element) continue;
        if (element.offsetTop <= reference) current = entry.entryId;
        else break;
      }
      const next = current ?? roundNavEntries[0]?.entryId ?? null;
      setCurrentRoundEntryId((previous) => (previous === next ? previous : next));
    };
    const schedule = () => {
      if (roundNavFrameRef.current !== null) return;
      roundNavFrameRef.current = requestAnimationFrame(update);
    };
    schedule();
    chat.addEventListener("scroll", schedule, { passive: true });
    return () => {
      chat.removeEventListener("scroll", schedule);
      if (roundNavFrameRef.current !== null) cancelAnimationFrame(roundNavFrameRef.current);
      roundNavFrameRef.current = null;
    };
  }, [collapsed, roundNavEntries]);

  const jumpToRoundEntry = useCallback((entry: RoundNavEntry) => {
    const chat = chatRef.current;
    if (!chat) return;
    const element = chat.querySelector<HTMLElement>(`[data-message-id="${entry.entryId}"]`);
    if (!element) return;
    chat.scrollTo({
      top: Math.max(0, element.offsetTop - chat.clientHeight * ROUND_NAV_JUMP_OFFSET_RATIO),
      behavior: "smooth",
    });
  }, []);

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
  }, [collapsed, session.session_id, scrollToBottom]);

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
        <SubagentAvatar name={session.name || session.session_id} />
        {session.name || session.session_id.slice(0, SID_DISPLAY_LEN)}
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
        <RoundNavRail entries={roundNavEntries} currentEntryId={currentRoundEntryId} onJump={jumpToRoundEntry} />
      </div>
    )}
  </div>
  );
}
