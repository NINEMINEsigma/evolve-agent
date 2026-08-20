import { useMemo } from "react";
import JsonView from "react18-json-view";
import "react18-json-view/src/style.css";
import { ChatMessage, ContentBlock, MessageContent } from "../types";
import MarkdownRenderer from "./primitives/MarkdownRenderer";
import { renderToolResult } from "./ToolResultRenderer";
import DiffBlock from "./DiffBlock";
import { extractPartialStringField } from "../utils/partialJson";

export function contentToText(content: MessageContent): string {
  if (typeof content === "string") return content;
  return content
    .map((block) => (block.type === "text" ? block.text : block.type === "image_url" ? "[image_url]" : block.type === "input_audio" ? "[input_audio]" : ""))
    .join("\n");
}

function formatReasoningDuration(ms: number): string {
  const totalSeconds = Math.round(ms / 1000);
  const mins = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  if (mins > 0) {
    return `Thought for ${mins} minute${mins > 1 ? "s" : ""} ${secs} second${secs > 1 ? "s" : ""}`;
  }
  return `Thought for ${secs} second${secs > 1 ? "s" : ""}`;
}

function renderBlocksContent(
  content: MessageContent,
  roleClass: string,
  messageId: string,
  onImageClick: (src: string) => void
) {
  if (typeof content === "string") {
    return <pre className={`message-text message-text-${roleClass}`}>{content}</pre>;
  }

  if (Array.isArray(content)) {
    const blocks = content as ContentBlock[];
    return (
      <div className="message-blocks">
        {blocks.map((block, idx) => {
          if (block.type === "text") {
            return (
              <pre key={`${messageId}-txt-${idx}`} className={`message-text message-text-${roleClass}`}>
                {block.text}
              </pre>
            );
          }
          if (block.type === "image_url") {
            const src = block.image_url.url;
            return (
              <a
                key={`${messageId}-img-${idx}`}
                href="#"
                onClick={(e) => { e.preventDefault(); onImageClick(src); }}
                className="message-img-link"
              >
                <img src={src} alt={`图片 ${idx + 1}`} className="message-img-thumb" />
              </a>
            );
          }
          if (block.type === "input_audio") {
            const dataUrl = block.input_audio.data.startsWith("data:")
              ? block.input_audio.data
              : `data:audio/${block.input_audio.format};base64,${block.input_audio.data}`;
            return (
              <div key={`${messageId}-audio-${idx}`} className="message-audio">
                <audio controls src={dataUrl} className="message-audio-player" />
              </div>
            );
          }
          return null;
        })}
      </div>
    );
  }

  return <pre className={`message-text message-text-${roleClass}`}>{String(content)}</pre>;
}

function ContextExtension({ message }: { message: ChatMessage }) {
  const hasSuffix = message.messageSuffix || message.dynamicMessageSuffix;
  if (!hasSuffix) return null;
  return (
    <details className="context-extension-block">
      <summary className="context-extension-summary">上下文扩展</summary>
      <div className="context-extension-content">
        {message.dynamicMessageSuffix && (
          <pre className="context-extension-part">{message.dynamicMessageSuffix}</pre>
        )}
        {message.messageSuffix && (
          <pre className="context-extension-part">{message.messageSuffix}</pre>
        )}
      </div>
    </details>
  );
}

interface MessageBodyProps {
  message: ChatMessage;
  streaming?: boolean;
  onImageClick: (src: string) => void;
}

export default function MessageBody({ message, streaming, onImageClick }: MessageBodyProps) {
  const m = message;
  const textContent = contentToText(m.content);

  const reasoningLabel = useMemo(() => {
    if (m.reasoningDuration != null) {
      return formatReasoningDuration(m.reasoningDuration);
    }
    if (streaming && m.reasoningContent) {
      return "Thinking...";
    }
    return "Thought process";
  }, [m.reasoningDuration, streaming, m.reasoningContent]);

  if (m.role === "assistant") {
    // streaming 且有 tool_call 参数增量缓冲：打字机渲染（多 tool_call 场景下已定型的 toolArgs 不阻止后续增量显示）
    const hasToolCallDelta = streaming && m.toolName && m.activeToolCallKey && m.toolArgsRawMap?.[m.activeToolCallKey] !== undefined;
    return (
      <>
        {m.reasoningContent && (
          <details className="reasoning-block">
            <summary className="reasoning-summary">{reasoningLabel}</summary>
            <div className="reasoning-content">{m.reasoningContent}</div>
          </details>
        )}
        {typeof m.content === "string" ? (
          <MarkdownRenderer content={textContent} streaming={streaming} onImageClick={onImageClick} />
        ) : (
          renderBlocksContent(m.content, m.role, m.id, onImageClick)
        )}
        {!streaming && (m.contentDuration != null || (m.tokensPerSecond != null && m.tokensPerSecond > 0)) && (
          <div className="message-metrics" style={{ display: "flex", gap: "0.75rem", fontSize: "0.75rem", color: "var(--text-secondary, #888)", marginTop: "0.25rem" }}>
            {m.contentDuration != null && m.contentDuration > 0 && (
              <span>Output: {formatReasoningDuration(m.contentDuration)}</span>
            )}
            {m.tokensPerSecond != null && m.tokensPerSecond > 0 && (
              <span>{m.tokensPerSecond} tokens/s</span>
            )}
            {m.totalTokens != null && m.totalTokens > 0 && (
              <span>{m.totalTokens} tokens</span>
            )}
          </div>
        )}
        {hasToolCallDelta && (() => {
          const raw = m.toolArgsRawMap![m.activeToolCallKey!];
          if (m.toolName === "Write") {
            const partialContent = extractPartialStringField(raw, "content");
            if (partialContent !== null) {
              return <DiffBlock oldText="" newText={partialContent} />;
            }
          }
          return (
            <div className="tool-args-raw-stream">
              <span className="tool-args-raw-label">{m.emoji || "⚡"} {m.toolName} 正在生成参数…</span>
              <pre className="tool-args-raw-content">{raw}</pre>
            </div>
          );
        })()}
        <ContextExtension message={m} />
        {streaming && <span className="streaming-cursor" />}
      </>
    );
  }

  if (m.role === "user") {
    return (
      <>
        {renderBlocksContent(m.content, m.role, m.id, onImageClick)}
        <ContextExtension message={m} />
      </>
    );
  }

  if (m.role === "tool") {
    // tool_call（有 toolArgs）
    if (m.toolArgs) {
      // Write tool_call：content + path 字段同时存在时显示为全绿行 diff
      if (typeof m.toolArgs.content === "string" && typeof m.toolArgs.path === "string") {
        const isAppend = m.toolArgs.mode === "append";
        return (
          <>
            {isAppend && <div className="diff-mode-label">追加</div>}
            <DiffBlock oldText="" newText={m.toolArgs.content} />
          </>
        );
      }
      // 其他 tool_call：用 JsonView 渲染参数对象
      return (
        <div className="tool-json-view">
          <JsonView src={m.toolArgs} collapsed={1} displaySize collapseStringsAfterLength={99999} />
        </div>
      );
    }
    // tool_result：尝试 JSON 渲染
    const contentStr = typeof m.content === "string" ? m.content : "";
    try {
      const parsed = JSON.parse(contentStr);
      const specialized = renderToolResult(m.toolName, parsed, onImageClick);
      if (specialized) {
        return (
          <>
            {specialized}
            <ContextExtension message={m} />
          </>
        );
      }
      return (
        <>
          <div className="tool-json-view">
            <JsonView src={parsed} collapsed={2} displaySize collapseStringsAfterLength={99999} />
          </div>
          <ContextExtension message={m} />
        </>
      );
    } catch {
      // parse 失败：纯文本 fallback
      return renderBlocksContent(m.content, m.role, m.id, onImageClick);
    }
  }

  return renderBlocksContent(m.content, m.role, m.id, onImageClick);
}

export { renderBlocksContent };