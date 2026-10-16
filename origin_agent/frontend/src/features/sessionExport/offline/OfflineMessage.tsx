/**
 * 离线单条消息。
 *
 * 复用正式内容组件（MessageBody / ToolCallCard / EmbeddedToolMessages / DiffBlock
 * 等），只复制壳布局职责与公开 data-* 契约。不渲染编辑/删除/审批/重新生成按钮；
 * 工具详情默认折叠、可展开，原始 JSON 始终可在嵌入数据中查看。
 */

import { memo, useState } from "react";
import type { ChatMessage } from "../../../types";
import MessageBody from "../../../components/MessageBody";
import MessageAttachments from "../../../components/MessageAttachments";
import ToolCallCard from "../../../components/ToolCallCard";
import { contentToText, isLongChatMessage, toolCallSummary } from "../../chat/messageCollapse";
import { useMessageRenderEnvironment } from "../../../components/primitives/MessageRenderEnvironment";
import { hueFromString } from "../../../utils/color";
import { exportLabels } from "../labels";

const CHINESE_NICKNAME_PREFIXES = new Set(["\u5c0f", "\u963f", "\u8001", "\u5927"]);

function getInitials(name: string): string {
  if (!name) return "";
  const first = name.slice(0, 1);
  if (name.length >= 2 && CHINESE_NICKNAME_PREFIXES.has(first)) {
    return name.slice(-1).toUpperCase();
  }
  return first.toUpperCase();
}

function getAvatarStyle(name?: string): React.CSSProperties {
  if (!name) return { backgroundColor: "#666" };
  return { backgroundColor: `hsl(${hueFromString(name)}, 65%, 45%)` };
}

const OfflineMessage = memo(function OfflineMessage({ message, onImageClick }: { message: ChatMessage; onImageClick: (src: string) => void }) {
  const m = message;
  // 工具详情默认可折叠；普通长消息默认展开（折叠不得丢数据）。
  const [toolCollapsed, setToolCollapsed] = useState(true);
  const [contentCollapsed, setContentCollapsed] = useState(false);
  const environment = useMessageRenderEnvironment();
  const textContent = contentToText(m.content);
  const toolSummary = toolCallSummary(m);
  const isTool = m.role === "tool";
  const isLong = isLongChatMessage(m);
  const displayName = m.characterName || (m.role === "user" ? "User" : m.role === "assistant" ? "Assistant" : undefined);

  if (m.isSystemStatus) {
    return (
      <div className="message message-system-status" data-message-id={m.id} data-chat-scope="message" data-message-role="system">
        <div className="message-system-status-content">{textContent}</div>
      </div>
    );
  }

  return (
    <div
      className={`message message-${m.role}`}
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
        {m.toolCard ? (
          <ToolCallCard
            message={{ ...m, collapsed: toolCollapsed }}
            onImageClick={onImageClick}
            onToggleCollapse={() => setToolCollapsed((value) => !value)}
            showSystemUserMessages
          />
        ) : isTool ? (
          <div className="tool-call-block" data-chat-scope="tool-call">
            <button
              type="button"
              className={`tool-call-summary ${toolCollapsed ? "" : "tool-call-summary-open"}`}
              onClick={() => setToolCollapsed((value) => !value)}
              title={toolSummary}
            >
              <span className="tool-call-summary-text">{toolSummary}</span>
            </button>
            {!toolCollapsed && (
              <div className={`tool-call-detail${m.isError ? " tool-call-detail-error" : ""}`} data-chat-scope="tool-detail">
                <MessageBody message={m} onImageClick={onImageClick} />
                <MessageAttachments message={m} onImageClick={onImageClick} resolveResource={environment.resolveResource} />
                {m.toolCallMeta && (
                  <div className="tool-call-meta">
                    {exportLabels.applied} {m.toolCallMeta.application_time}
                    {m.toolCallMeta.approval_duration_ms > 0 && ` | ${exportLabels.approval} ${m.toolCallMeta.approval_duration_ms}ms`}
                    {m.toolCallMeta.invocation_duration_ms !== undefined && ` | ${exportLabels.invocation} ${m.toolCallMeta.invocation_duration_ms}ms`}
                  </div>
                )}
              </div>
            )}
          </div>
        ) : (
          <div className={`message-content${isLong && contentCollapsed ? " message-content-collapsed" : ""}`} data-chat-scope="content">
            <MessageBody message={m} onImageClick={onImageClick} />
            <MessageAttachments message={m} onImageClick={onImageClick} resolveResource={environment.resolveResource} />
          </div>
        )}

        {!isTool && isLong && (
          <div className="message-toolbar" data-chat-scope="toolbar">
            <div className="message-actions">
              <button type="button" onClick={() => setContentCollapsed((value) => !value)}>
                {contentCollapsed ? exportLabels.expand : exportLabels.collapse}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
});

export default OfflineMessage;