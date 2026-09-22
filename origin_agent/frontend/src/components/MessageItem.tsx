import { memo, useState, type WheelEvent } from "react";
import { ChatMessage, MessageContent } from "../types";
import MessageBody from "./MessageBody";
import { contentToText, isLongChatMessage, toolCallSummary } from "../features/chat/messageCollapse";
import MessageEditor from "./MessageEditor";
import MessageAttachments from "./MessageAttachments";
import ToolCallCard from "./ToolCallCard";

function hashString(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const chr = str.charCodeAt(i);
    hash = ((hash << 5) - hash) + chr;
    hash |= 0;
  }
  return Math.abs(hash);
}

function hueFromString(str: string): number {
  return hashString(str) % 360;
}

const CHINESE_NICKNAME_PREFIXES = new Set(["小", "阿", "老", "大"]);

function getInitials(name: string): string {
  if (!name) return "";
  const first = name.slice(0, 1);
  if (name.length >= 2 && CHINESE_NICKNAME_PREFIXES.has(first)) {
    return name.slice(-1).toUpperCase();
  }
  return first.toUpperCase();
}

function getAvatarStyle(name?: string): React.CSSProperties {
  if (!name) {
    return { backgroundColor: "#666" };
  }
  return { backgroundColor: `hsl(${hueFromString(name)}, 65%, 45%)` };
}

const MessageItem = memo(function MessageItem({
  message,
  archived,
  onImageClick,
  onToggleCollapse,
  onEditMessage,
  onDeleteMessages,
  onDeleteSingleMessage,
  onRegenerateResponse,
  isLastUserMessage,
  isAfterLastUser,
  streaming,
  waiting,
  agents,
  onToggleMessageVisibility,
  onUserHeightMutation,
  animateEntry,
}: {
  message: ChatMessage;
  archived: boolean;
  onImageClick: (src: string) => void;
  onToggleCollapse: (id: string) => void;
  onEditMessage: (id: string, content: MessageContent) => void | Promise<void>;
  onDeleteMessages?: (count: number) => void;
  onDeleteSingleMessage?: (index: number) => void;
  onRegenerateResponse?: (messageIndex: number) => void;
  isLastUserMessage?: boolean;
  isAfterLastUser?: boolean;
  streaming?: boolean;
  waiting?: boolean;
  agents?: string[];
  onToggleMessageVisibility?: (messageId: string, agentName: string) => void;
  onUserHeightMutation?: () => void;
  animateEntry?: boolean;
}) {
  const m = message;
  const [editing, setEditing] = useState(false);

  const textContent = contentToText(m.content);
  const toolSummary = toolCallSummary(m);
  const isLong = isLongChatMessage(m);
  const isTool = m.role === "tool";
  const toolCollapsed = isTool && m.collapsed !== false;
  const collapsed = !isTool && !streaming && isLong && m.collapsed !== false;
  const canEdit = !archived && !streaming && (m.role === "user" || m.role === "assistant") && typeof m.messageIndex === "number";
  const canDelete = !archived && !streaming && isLastUserMessage && typeof m.messageIndex === "number";
  const canDeleteSingle = !archived && !streaming && isAfterLastUser
    && !m.isSystemStatus && m.role !== "user"
    && (!m.toolCard || typeof m.toolCard.result?.historyIndex === "number");
  const deleteIndex = m.toolCard?.result?.historyIndex ?? m.messageIndex;
  const canRegenerate = !archived && !streaming && m.role === "user" && isLastUserMessage && typeof m.messageIndex === "number";

  const handoffWheelAtBoundary = (event: WheelEvent<HTMLDivElement>) => {
    const current = event.currentTarget;
    const { scrollTop, scrollHeight, clientHeight } = current;
    const canScroll = scrollHeight > clientHeight;
    if (!canScroll || event.deltaY === 0) return;

    const scrollingUp = event.deltaY < 0;
    const scrollingDown = event.deltaY > 0;
    const atTop = scrollTop <= 0;
    const atBottom = scrollTop + clientHeight >= scrollHeight - 1;
    const shouldHandoff = (scrollingUp && atTop) || (scrollingDown && atBottom);
    if (!shouldHandoff) return;

    const chatArea = current.closest(".chat-area");
    if (!(chatArea instanceof HTMLElement)) return;

    event.preventDefault();
    chatArea.scrollTop += event.deltaY;
  };

  const displayName = m.characterName || (m.role === "user" ? "User" : m.role === "assistant" ? "Assistant" : undefined);
  const showMeta = m.visibleCharacters != null || m.requiresResponse != null;

  // 系统状态消息：居中灰色气泡，无头像、无编辑/删除/重新生成按钮
  if (m.isSystemStatus) {
    return (
      <div className="message message-system-status" data-message-id={m.id} data-chat-scope="message" data-message-role="system">
        <div className="message-system-status-content">{textContent}</div>
      </div>
    );
  }

  return (
    <div
      className={`message message-${m.role}${streaming ? " message-streaming" : ""}${animateEntry ? " message-new" : ""}`}
      data-message-id={m.id}
      data-chat-scope="message"
      data-message-role={m.role}
      data-character-name={displayName}
      style={{ "--msg-hue": hueFromString(displayName || "") } as React.CSSProperties}
    >
      {(m.role === "user" || m.role === "assistant" || m.role === "error") && (
        <div className="message-avatar-wrapper" data-tooltip={displayName || m.role}>
          <div className="message-avatar" style={m.role === "user" || m.role === "assistant" ? getAvatarStyle(displayName) : undefined}>
            {m.role === "error" ? "!" : getInitials(displayName || "")}
          </div>
        </div>
      )}
      <div className="message-bubble" data-chat-scope="bubble">
        {m.toolCard && !editing ? (
          <ToolCallCard
            message={m}
            onImageClick={onImageClick}
            onToggleCollapse={onToggleCollapse}
            onUserHeightMutation={onUserHeightMutation}
          />
        ) : isTool && !editing ? (
          <div className="tool-call-block" data-chat-scope="tool-call">
            <button
              type="button"
              className={`tool-call-summary ${toolCollapsed ? "" : "tool-call-summary-open"}`}
              onClick={() => {
                onUserHeightMutation?.();
                onToggleCollapse(m.id);
              }}
              title={toolSummary}
            >
              <span className="tool-call-summary-text">{toolSummary}</span>
            </button>
            {!toolCollapsed && (
              <div className={`tool-call-detail message-content-collapsed${m.isError ? " tool-call-detail-error" : ""}`} data-chat-scope="tool-detail" onWheel={handoffWheelAtBoundary}>
                <MessageBody message={m} onImageClick={onImageClick} onUserHeightMutation={onUserHeightMutation} />
                <MessageAttachments message={m} onImageClick={onImageClick} />
                {m.toolCallMeta && (
                  <div className="tool-call-meta">
                    申请 {m.toolCallMeta.application_time}
                    {m.toolCallMeta.approval_duration_ms > 0 && ` | 审批 ${m.toolCallMeta.approval_duration_ms}ms`}
                    {m.toolCallMeta.invocation_duration_ms !== undefined && ` | 调用 ${m.toolCallMeta.invocation_duration_ms}ms`}
                  </div>
                )}
              </div>
            )}
          </div>
        ) : (
          <div
            className={`message-content ${collapsed && !editing ? "message-content-collapsed" : ""}`}
            data-chat-scope="content"
            onWheel={collapsed && !editing ? handoffWheelAtBoundary : undefined}
          >
            {editing ? (
              <MessageEditor
                message={m}
                onSave={async (content) => {
                  await onEditMessage(m.id, content);
                  setEditing(false);
                }}
                onCancel={() => setEditing(false)}
              />
            ) : (
              <MessageBody message={m} streaming={streaming} onImageClick={onImageClick} onUserHeightMutation={onUserHeightMutation} />
            )}
            <MessageAttachments message={m} onImageClick={onImageClick} />
          </div>
        )}

        <div className="message-toolbar" data-chat-scope="toolbar">
          <span className="message-meta">
            {m.edited ? "已编辑" : canEdit ? `#${m.messageIndex}` : ""}
            {showMeta && (
              <span className="message-meta-tags">
                {m.visibleCharacters != null && m.visibleCharacters.length > 0 && (
                  <span className="message-meta-tag" title={`Visible to: ${m.visibleCharacters.join(", ")}`}>
                    V {m.visibleCharacters.length}
                  </span>
                )}
                {m.requiresResponse && (
                  <span className="message-meta-tag message-meta-tag-response">
                    待响应
                  </span>
                )}
              </span>
            )}
          </span>
          <div className="message-actions">
            {!isTool && isLong && (
              <button type="button" onClick={() => {
                onUserHeightMutation?.();
                onToggleCollapse(m.id);
              }}>
                {collapsed ? "展开" : "收起"}
              </button>
            )}
            {canEdit && !editing && (
              <button type="button" onClick={() => setEditing(true)}>
                编辑
              </button>
            )}
            {canDelete && (
              <button type="button" onClick={() => {
                const countStr = prompt("删除最后几轮对话？", "1");
                const count = parseInt(countStr || "1", 10);
                if (count > 0) onDeleteMessages!(count);
              }}
              >
                删除
              </button>
            )}
            {canDeleteSingle && deleteIndex != null && (
              <button type="button" onClick={() => onDeleteSingleMessage!(deleteIndex)}
              >
                删除此条
              </button>
            )}
            {canRegenerate && (
              <button type="button" disabled={waiting} onClick={() => onRegenerateResponse!(m.messageIndex!)}>
                重新生成
              </button>
            )}
          </div>
          {agents && agents.length > 0 && message.visibleCharacters != null && (
            <div className="message-visibility-row">
              {agents.map((agent) => {
                const curVisible = message.visibleCharacters || [];
                const isAll = curVisible.includes("all-agents");
                const isVisible = isAll || curVisible.includes(agent);
                const isResponse = (message.responseCharacters || []).includes(agent);
                const stateLabel = isResponse ? agent + " · 需响应" : isVisible ? agent + " · 仅可见" : agent + " · 隐藏";
                const stateClass = isResponse ? "state-response" : isVisible ? "state-visible" : "state-none";
                return (
                  <button
                    key={agent}
                    type="button"
                    className={`message-visibility-dot ${stateClass}`}
                    onClick={() => onToggleMessageVisibility?.(message.id, agent)}
                    data-tooltip={stateLabel}
                    title={stateLabel}
                  />
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
});

export default MessageItem;