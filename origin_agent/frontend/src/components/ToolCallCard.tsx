import type { ChatMessage } from "../types";
import MessageBody from "./MessageBody";
import MessageAttachments from "./MessageAttachments";
import { toolCardSummary } from "../features/chat/toolCards";

interface ToolCallCardProps {
  message: ChatMessage;
  onImageClick: (src: string) => void;
  onToggleCollapse: (id: string) => void;
  onUserHeightMutation?: () => void;
}

export default function ToolCallCard({
  message,
  onImageClick,
  onToggleCollapse,
  onUserHeightMutation,
}: ToolCallCardProps) {
  const card = message.toolCard;
  if (!card) return null;
  const collapsed = message.collapsed !== false;
  const resultMessage: ChatMessage | null = card.result ? {
    id: `${message.id}:result`,
    role: "tool",
    content: card.result.content,
    toolName: card.request.toolName,
    imageMarkdown: card.result.imageMarkdown,
    downloadInfo: card.result.downloadInfo,
    toolCallMeta: card.result.toolCallMeta,
    isError: card.result.isError,
  } : null;
  const requestMessage: ChatMessage = {
    id: `${message.id}:request`,
    role: "tool",
    content: `${message.characterName ? `${message.characterName} ` : ""}⚡ ${card.request.toolName || "tool"}`,
    toolName: card.request.toolName,
    toolArgs: card.request.args,
  };

  return (
    <div className={`tool-call-card tool-call-card-${card.status}`} data-chat-scope="tool-call">
      <button
        type="button"
        className={`tool-call-summary ${collapsed ? "" : "tool-call-summary-open"}`}
        onClick={() => {
          onUserHeightMutation?.();
          onToggleCollapse(message.id);
        }}
        title={toolCardSummary(card)}
      >
        <span className="tool-call-summary-text">{toolCardSummary(card)}</span>
      </button>
      {!collapsed && (
        <div className="tool-call-detail message-content-collapsed" data-chat-scope="tool-detail">
          <section className="tool-card-section tool-card-request">
            <div className="tool-card-section-title">请求参数</div>
            {card.request.argsRaw && (!card.request.args || Object.keys(card.request.args).length === 0) ? (
              <pre className="tool-args-raw-content">{card.request.argsRaw}</pre>
            ) : (
              <MessageBody message={requestMessage} onImageClick={onImageClick} onUserHeightMutation={onUserHeightMutation} />
            )}
          </section>
          <section className="tool-card-section tool-card-result">
            <div className="tool-card-section-title">工具结果</div>
            {resultMessage && card.result ? (
              <>
                <MessageBody message={resultMessage} onImageClick={onImageClick} onUserHeightMutation={onUserHeightMutation} />
                <MessageAttachments message={resultMessage} onImageClick={onImageClick} />
                {card.result.toolCallMeta && (
                  <div className="tool-call-meta">
                    申请 {card.result.toolCallMeta.application_time}
                    {card.result.toolCallMeta.approval_duration_ms > 0 && ` | 审批 ${card.result.toolCallMeta.approval_duration_ms}ms`}
                    {card.result.toolCallMeta.invocation_duration_ms !== undefined && ` | 调用 ${card.result.toolCallMeta.invocation_duration_ms}ms`}
                  </div>
                )}
              </>
            ) : (
              <div className="tool-card-result-placeholder">
                {card.status === "missing_result" ? "未返回结果" : "工具执行中…"}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
