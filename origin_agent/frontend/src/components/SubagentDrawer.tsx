import { useState, useRef, useEffect } from "react";
import { SubagentSession, SubagentMessage } from "../types";

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

const ROLE_LABEL: Record<string, string> = {
  user: "主 Agent",
  assistant: "子 Agent",
  reasoning: "思考",
  tool_call: "工具调用",
  tool_result: "工具结果",
  approval_pending: "等待审批",
  approval_decision: "审批结果",
  status: "状态",
  completed: "完成",
  terminated: "终止",
};

function bubbleVariant(role: string): string {
  switch (role) {
    case "user": return "user";
    case "assistant": return "assistant";
    case "reasoning": return "reasoning";
    case "tool_call": return "tool-call";
    case "tool_result": return "tool-result";
    case "approval_pending": return "pending";
    case "approval_decision": return "decision";
    case "status":
    case "completed":
    case "terminated":
      return "status";
    default:
      return "tool";
  }
}

export default function SubagentDrawer({
  open,
  onClose,
  subagentSessions,
}: SubagentDrawerProps) {
  const [collapsedSessions, setCollapsedSessions] = useState<Set<string>>(new Set());

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
          {items.map((session) => (
            <SubagentCard
              key={session.session_id}
              session={session}
              collapsed={collapsedSessions.has(session.session_id)}
              onToggleCollapse={() => toggleCollapse(session.session_id)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function SubagentCard({ session, collapsed, onToggleCollapse }: { session: SubagentSession; collapsed: boolean; onToggleCollapse: () => void }) {
  const chatRef = useRef<HTMLDivElement>(null);
  const isInactive = session.status === "terminated" || session.status === "completed";

  useEffect(() => {
    if (!collapsed && chatRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight;
    }
  }, [collapsed, session.feedback.length]);

  return (
    <div className={`subagent-card ${isInactive ? "inactive" : "active"}`}>
      <div className="subagent-info" onClick={onToggleCollapse}>
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
        <div className="subagent-chat subagent-chat-scroll" ref={chatRef}>
          {session.feedback.length === 0 && session.pending_approvals.length === 0 && (
            <div className="drawer-empty subagent-chat-empty">等待子会话响应...</div>
          )}
          {session.feedback.map((msg, i) => (
            <SubagentBubble key={i} msg={msg} />
          ))}
          {session.pending_approvals.map((pa) => (
            <div key={pa.tool_call_id} className="subagent-bubble subagent-bubble-pending">
              <span className="subagent-bubble-role">待审批</span>
              <div className="subagent-approval-tool">{pa.tool_name}</div>
              <pre className="subagent-approval-args">
                {JSON.stringify(pa.arguments, null, 2)}
              </pre>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SubagentBubble({ msg }: { msg: SubagentMessage }) {
  const role = (msg.role || "msg").toLowerCase();
  const label = ROLE_LABEL[role] ?? (msg.role || "MSG");
  const variant = bubbleVariant(role);

  if (role === "tool_call") {
    return (
      <div className={`subagent-bubble subagent-bubble-${variant}`}>
        <span className="subagent-bubble-role">{label}</span>
        <div className="subagent-approval-tool">⚡ {msg.tool_name}</div>
        {msg.tool_args && Object.keys(msg.tool_args).length > 0 && (
          <pre className="subagent-approval-args">
            {JSON.stringify(msg.tool_args, null, 2)}
          </pre>
        )}
      </div>
    );
  }

  if (role === "tool_result") {
    return (
      <div className={`subagent-bubble subagent-bubble-${variant}`}>
        <span className="subagent-bubble-role">{label}</span>
        {msg.tool_name && (
          <div className="subagent-approval-tool">✓ {msg.tool_name}</div>
        )}
        <pre className="subagent-approval-args">{msg.content || "(空)"}</pre>
      </div>
    );
  }

  if (role === "reasoning") {
    return (
      <div className={`subagent-bubble subagent-bubble-${variant}`}>
        <span className="subagent-bubble-role">{label}</span>
        <div className="subagent-bubble-text">{msg.reasoning || msg.content || "(空)"}</div>
      </div>
    );
  }

  if (role === "approval_pending") {
    return (
      <div className={`subagent-bubble subagent-bubble-${variant}`}>
        <span className="subagent-bubble-role">{label}</span>
        <div className="subagent-approval-tool">⏸ {msg.tool_name}</div>
        {msg.tool_args && Object.keys(msg.tool_args).length > 0 && (
          <pre className="subagent-approval-args">
            {JSON.stringify(msg.tool_args, null, 2)}
          </pre>
        )}
      </div>
    );
  }

  if (role === "approval_decision") {
    return (
      <div className={`subagent-bubble subagent-bubble-${variant}`}>
        <span className="subagent-bubble-role">{label}</span>
        <div className="subagent-bubble-text">
          {msg.tool_name ? `${msg.tool_name}: ${msg.content}` : msg.content}
        </div>
      </div>
    );
  }

  return (
    <div className={`subagent-bubble subagent-bubble-${variant}`}>
      <span className="subagent-bubble-role">{label}</span>
      <div className="subagent-bubble-text">{msg.content || "(空)"}</div>
    </div>
  );
}