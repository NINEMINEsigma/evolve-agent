import { memo, useMemo, useState, type WheelEvent } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ChatMessage, ContentBlock } from "../types";
import CodeBlock from "./CodeBlock";
import PlaylistPlayer from "./PlaylistPlayer";

const LONG_MESSAGE_CHARS = 1200;
const LONG_MESSAGE_LINES = 18;

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

const MessageItem = memo(function MessageItem({ message, archived, onImageClick, onToggleCollapse, onEditMessage, streaming }: {
  message: ChatMessage;
  archived: boolean;
  onImageClick: (src: string) => void;
  onToggleCollapse: (id: string) => void;
  onEditMessage: (id: string, content: string) => void | Promise<void>;
  streaming?: boolean;
}) {
  const m = message;
  const [editing, setEditing] = useState(false);
  const textContent = typeof m.content === "string" ? m.content : "";
  const [draft, setDraft] = useState(textContent);
  const lineCount = textContent.split("\n").length;
  const isLong = textContent.length > LONG_MESSAGE_CHARS || lineCount > LONG_MESSAGE_LINES;
  const collapsed = m.collapsed !== false;
  const canEdit = !archived && !streaming && typeof m.messageIndex === "number" && typeof m.content === "string";

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

  const renderUserContent = () => {
    const content = m.content;
    if (typeof content === "string") {
      return <pre className={`message-text message-text-${m.role}`}>{content}</pre>;
    }

    if (Array.isArray(content)) {
      const blocks = content as ContentBlock[];
      return (
        <div className="message-user-mixed">
          {blocks.map((block, idx) => {
            if (block.type === "text") {
              return (
                <span key={`${m.id}-txt-${idx}`} className={`message-text message-text-${m.role}`}>
                  {block.text}
                </span>
              );
            }
            if (block.type === "image_url") {
              const src = block.image_url.url;
              return (
                <a
                  key={`${m.id}-img-${idx}`}
                  href="#"
                  onClick={(e) => { e.preventDefault(); onImageClick(src); }}
                  className="message-user-img-link"
                >
                  <img src={src} alt={`图片 ${idx + 1}`} className="message-user-thumb" />
                </a>
              );
            }
            return null;
          })}
        </div>
      );
    }

    return <pre className={`message-text message-text-${m.role}`}>{String(content)}</pre>;
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

    if (m.role === "agent") {
      return (
        <>
          {m.reasoningContent && (
            <details className="reasoning-block">
              <summary className="reasoning-summary">思考过程</summary>
              <div className="reasoning-content">{m.reasoningContent}</div>
            </details>
          )}
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
            {textContent || (m.reasoningContent ? "_仅包含思考内容_" : "")}
          </ReactMarkdown>
          {streaming && <span className="streaming-cursor" />}
        </>
      );
    }

    if (m.role === "user") {
      return renderUserContent();
    }

    return <pre className={`message-text message-text-${m.role}`}>{textContent}</pre>;
  };

  return (
    <div className={`message message-${m.role}`} data-message-id={m.id}>
      <div className="message-avatar">
        {m.role === "user" ? "U" : m.role === "agent" ? "⚡" : m.role === "error" ? "!" : m.role === "tool" ? "🔧" : "●"}
      </div>
      <div className="message-bubble">
        {m.role === "tool" && !editing ? (
          <div className="tool-call-block">
            <button
              type="button"
              className={`tool-call-summary ${collapsed ? "" : "tool-call-summary-open"}`}
              onClick={() => onToggleCollapse(m.id)}
            >
              {textContent.length > 80 ? textContent.slice(0, 80) + '...' : textContent}
            </button>
            {!collapsed && (
              <div className="tool-call-detail message-content-collapsed" onWheel={handoffWheelAtBoundary}>
                <pre className="message-text message-text-tool">{textContent}</pre>
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
          </div>
        </div>
      </div>
    </div>
  );
});

export default MessageItem;