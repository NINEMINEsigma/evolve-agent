import { memo, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ChatMessage } from "../types";
import CodeBlock from "./CodeBlock";
import PlaylistPlayer from "./PlaylistPlayer";

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

const MessageItem = memo(function MessageItem({ message, onImageClick }: {
  message: ChatMessage;
  onImageClick: (src: string) => void;
}) {
  const m = message;

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

  return (
    <div className={`message message-${m.role}`}>
      <div className="message-avatar">
        {m.role === "user" ? "U" : m.role === "agent" ? "⚡" : m.role === "error" ? "!" : m.role === "tool" ? "🔧" : "●"}
      </div>
      <div className="message-bubble">
        {m.role === "tool" ? (
          <details className="tool-call-block">
            <summary className="tool-call-summary">
              {m.content.length > 80 ? m.content.slice(0, 80) + '...' : m.content}
            </summary>
            <div className="tool-call-detail">
              <pre className="message-text message-text-tool">{m.content}</pre>
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
                  <a
                    href={m.downloadInfo.url}
                    className="download-btn"
                    download={m.downloadInfo.filename}
                  >
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
            </div>
          </details>
        ) : m.role === "agent" ? (
          <>
            {m.reasoningContent && (
              <details className="reasoning-block">
                <summary className="reasoning-summary">思考过程</summary>
                <div className="reasoning-content">{m.reasoningContent}</div>
              </details>
            )}
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={mdComponents}
            >
              {m.content}
            </ReactMarkdown>
          </>
        ) : (
          <pre className={`message-text message-text-${m.role}`}>{m.content}</pre>
        )}
      </div>
    </div>
  );
});

export default MessageItem;