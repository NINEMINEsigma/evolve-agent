import { memo, useMemo, useState, type WheelEvent } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ChatMessage, ContentBlock, MessageContent } from "../types";
import CodeBlock from "./CodeBlock";
import PlaylistPlayer from "./PlaylistPlayer";

const LONG_MESSAGE_CHARS = 1200;
const LONG_MESSAGE_LINES = 18;

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

const markdownComponentsBase = {
  code({ className, children, ...props }: any) {
    const match = /language-(\w+)/.exec(className || "");
    const code = String(children).replace(/\n$/, "");
    if (match) {
      return <CodeBlock language={match[1]} code={code} />;
    }
    return (
      <code className={className} {...props}>
        {children}
      </code>
    );
  },
  p({ children }: any) {
    return <p style={{ margin: "0.4em 0" }}>{children}</p>;
  },
  ul({ children }: any) {
    return <ul style={{ margin: "0.3em 0", paddingLeft: "1.5em" }}>{children}</ul>;
  },
  ol({ children }: any) {
    return <ol style={{ margin: "0.3em 0", paddingLeft: "1.5em" }}>{children}</ol>;
  },
  table({ children }: any) {
    return (
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", width: "100%" }}>{children}</table>
      </div>
    );
  },
  th({ children }: any) {
    return (
      <th style={{ border: "1px solid #444", padding: "6px 10px", background: "#2a2a2a" }}>
        {children}
      </th>
    );
  },
  td({ children }: any) {
    return <td style={{ border: "1px solid #444", padding: "6px 10px" }}>{children}</td>;
  },
  a({ href, children }: any) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    );
  },
};

const MessageItem = memo(function MessageItem({ message, archived, onImageClick, onToggleCollapse, onEditMessage, onDeleteMessages, onRegenerateResponse, isLastUserMessage, streaming, agents, onToggleMessageVisibility }: {
  message: ChatMessage;
  archived: boolean;
  onImageClick: (src: string) => void;
  onToggleCollapse: (id: string) => void;
  onEditMessage: (id: string, content: string) => void | Promise<void>;
  onDeleteMessages?: (count: number) => void;
  onRegenerateResponse?: () => void;
  isLastUserMessage?: boolean;
  streaming?: boolean;
  agents?: string[];
  onToggleMessageVisibility?: (messageId: string, agentName: string) => void;
}) {
  const m = message;
  const [editing, setEditing] = useState(false);

  const contentToText = (content: MessageContent): string => {
    if (typeof content === "string") return content;
    return content
      .map((block) => (block.type === "text" ? block.text : "[image_url]"))
      .join("\n");
  };

  const textContent = contentToText(m.content);
  const [draft, setDraft] = useState(textContent);
  const lineCount = textContent.split("\n").length;
  const isLong = textContent.length > LONG_MESSAGE_CHARS || lineCount > LONG_MESSAGE_LINES;
  const isTool = m.role === "tool";
  const toolCollapsed = isTool && !streaming && m.collapsed !== false;
  const collapsed = !isTool && !streaming && isLong && m.collapsed !== false;
  const canEdit = !archived && !streaming && typeof m.messageIndex === "number" && typeof m.content === "string";
  const canDelete = !archived && !streaming && isLastUserMessage;
  const canRegenerate = !archived && !streaming && m.role === "user" && isLastUserMessage;

  const mdComponents = useMemo(() => ({
    ...markdownComponentsBase,
    img({ src, alt }: any) {
      return (
        <a href="#" onClick={(e) => { e.preventDefault(); onImageClick(src!); }} className="message-img-link">
          <img src={src} alt={alt || ''} className="message-img" />
        </a>
      );
    },
  }), [onImageClick]);

  const formatReasoningDuration = (seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    if (mins > 0) {
      return `Thought for ${mins} minute${mins > 1 ? "s" : ""} ${secs} second${secs > 1 ? "s" : ""}`;
    }
    return `Thought for ${secs} second${secs > 1 ? "s" : ""}`;
  };

  const reasoningLabel = useMemo(() => {
    if (m.reasoningDuration != null) {
      return formatReasoningDuration(m.reasoningDuration);
    }
    if (streaming && m.reasoningContent) {
      return "Thinking...";
    }
    return "Thought process";
  }, [m.reasoningDuration, streaming, m.reasoningContent]);

  const saveEdit = async () => {
    const next = draft.trimEnd();
    if (next === m.content) {
      setEditing(false);
      return;
    }
    await onEditMessage(m.id, next);
    setEditing(false);
  };

  const cancelEdit = () => {
    setDraft(textContent);
    setEditing(false);
  };

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

  const renderAttachments = () => (
    <>
      {m.imageMarkdown && (() => {
        const md = m.imageMarkdown;
        const match = md.match(/!\[(.*?)\]\(([^)]+)\)/);
        const altText = match ? match[1] : "";
        const imgSrc = match ? match[2] : "";
        return imgSrc ? (
          <a href="#" onClick={(e) => { e.preventDefault(); onImageClick(imgSrc); }} className="tool-image-link">
            <img src={imgSrc} alt={altText} className="tool-image" />
          </a>
        ) : null;
      })()}
      {m.audioUrl && (
        <div className="tool-audio">
          <audio controls={true} autoPlay={m.audioAutoplay} src={m.audioUrl} className="tool-audio-player">
            您的浏览器不支持音频播放
          </audio>
        </div>
      )}
      {m.playlist && m.playlist.length > 0 && (
        <PlaylistPlayer playlist={m.playlist} autoplay={m.playlistAutoplay ?? true} />
      )}
      {m.downloadInfo && (
        <div className="tool-download">
          <a href={m.downloadInfo.url} className="download-btn" download={m.downloadInfo.filename}>
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
            下载 {m.downloadInfo.filename}
          </a>
          {m.downloadInfo.size != null && (
            <span className="download-size">（{(m.downloadInfo.size / 1024).toFixed(1)} KB）</span>
          )}
        </div>
      )}
    </>
  );

  const renderBlocksContent = (content: MessageContent, roleClass: string) => {
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
                <pre key={`${m.id}-txt-${idx}`} className={`message-text message-text-${roleClass}`}>
                  {block.text}
                </pre>
              );
            }
            if (block.type === "image_url") {
              const src = block.image_url.url;
              return (
                <a
                  key={`${m.id}-img-${idx}`}
                  href="#"
                  onClick={(e) => { e.preventDefault(); onImageClick(src); }}
                  className="message-img-link"
                >
                  <img src={src} alt={`图片 ${idx + 1}`} className="message-img-thumb" />
                </a>
              );
            }
            return null;
          })}
        </div>
      );
    }

    return <pre className={`message-text message-text-${roleClass}`}>{String(content)}</pre>;
  };

  const renderBody = () => {
    if (editing) {
      return (
        <div className="message-edit-box">
          <textarea
            className="message-edit-textarea"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={Math.min(Math.max(draft.split("\n").length, 4), 18)}
          />
          <div className="message-edit-actions">
            <button type="button" onClick={saveEdit}>保存</button>
            <button type="button" onClick={cancelEdit}>取消</button>
          </div>
        </div>
      );
    }

    if (m.role === "assistant") {
      return (
        <>
          {m.reasoningContent && (
            <details className="reasoning-block">
              <summary className="reasoning-summary">{reasoningLabel}</summary>
              <div className="reasoning-content">{m.reasoningContent}</div>
            </details>
          )}
          {typeof m.content === "string" ? (
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
              {textContent || ""}
            </ReactMarkdown>
          ) : (
            renderBlocksContent(m.content, m.role)
          )}
          {streaming && <span className="streaming-cursor" />}
        </>
      );
    }

    if (m.role === "user") {
      return renderBlocksContent(m.content, m.role);
    }

    return renderBlocksContent(m.content, m.role);
  };

  const displayName = m.characterName || (m.role === "user" ? "User" : m.role === "assistant" ? "Assistant" : undefined);
  const showMeta = m.visibleCharacters != null || m.requiresResponse != null;

  return (
    <div className={`message message-${m.role}`} data-message-id={m.id}>
      {(m.role === "user" || m.role === "assistant" || m.role === "error") && (
        <div className="message-avatar-wrapper" data-tooltip={displayName || m.role}>
          <div className="message-avatar" style={m.role === "user" || m.role === "assistant" ? getAvatarStyle(displayName) : undefined}>
            {m.role === "error" ? "!" : getInitials(displayName || "")}
          </div>
        </div>
      )}
      <div className="message-bubble">
        {isTool && !editing ? (
          <div className="tool-call-block">
            <button
              type="button"
              className={`tool-call-summary ${toolCollapsed ? "" : "tool-call-summary-open"}`}
              onClick={() => onToggleCollapse(m.id)}
            >
              {textContent.length > 80 ? textContent.slice(0, 80) + '...' : textContent}
            </button>
            {!toolCollapsed && (
              <div className="tool-call-detail message-content-collapsed" onWheel={handoffWheelAtBoundary}>
                {renderBlocksContent(m.content, "tool")}
                {renderAttachments()}
              </div>
            )}
          </div>
        ) : (
          <div
            className={`message-content ${collapsed && !editing ? "message-content-collapsed" : ""}`}
            onWheel={collapsed && !editing ? handoffWheelAtBoundary : undefined}
          >
            {renderBody()}
            {renderAttachments()}
          </div>
        )}
        <div className="message-toolbar">
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
            {isLong && (
              <button type="button" onClick={() => onToggleCollapse(m.id)}>
                {collapsed ? "展开" : "收起"}
              </button>
            )}
            {canEdit && !editing && (
              <button type="button" onClick={() => { setDraft(textContent); setEditing(true); }}>
                编辑
              </button>
            )}
            {canDelete && (
              <button type="button" onClick={() => {
                const countStr = prompt("删除最后几轮对话？", "1");
                const count = parseInt(countStr || "1", 10);
                if (count > 0) onDeleteMessages!(count);
              }}>
                删除
              </button>
            )}
            {canRegenerate && (
              <button type="button" onClick={() => onRegenerateResponse!()}>
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