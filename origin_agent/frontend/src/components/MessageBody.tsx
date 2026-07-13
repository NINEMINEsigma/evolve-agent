import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import rehypeRaw from "rehype-raw";
import type { Components } from "react-markdown";
import { ChatMessage, ContentBlock, MessageContent } from "../types";
import CodeBlock from "./CodeBlock";
import SafeHtml from "./SafeHtml";
import MermaidRenderer from "./MermaidRenderer";

// 当文本包含 script、style、link、iframe 等标签时，需要完整隔离渲染，避免 CSS/JS 污染外层页面
const SANDBOX_TAG_RE = /<script\b|<style\b|<link\b|<iframe\b|<object\b|<embed\b/i;
function needsSandbox(text: string): boolean {
  return SANDBOX_TAG_RE.test(text);
}

export function contentToText(content: MessageContent): string {
  if (typeof content === "string") return content;
  return content
    .map((block) => (block.type === "text" ? block.text : "[image_url]"))
    .join("\n");
}

function formatReasoningDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  if (mins > 0) {
    return `Thought for ${mins} minute${mins > 1 ? "s" : ""} ${secs} second${secs > 1 ? "s" : ""}`;
  }
  return `Thought for ${secs} second${secs > 1 ? "s" : ""}`;
}

const markdownComponentsBase: Components = {
  code({ inline, className, children, ...props }: React.HTMLAttributes<HTMLElement> & { inline?: boolean }) {
    const match = /language-(\w+)/.exec(className || "");
    const code = String(children).replace(/\n$/, "");
    if (!inline && match) {
      return <CodeBlock language={match[1]} code={code} />;
    }
    return (
      <code className={className} {...props}>
        {children}
      </code>
    );
  },
  p({ children }: React.HTMLAttributes<HTMLParagraphElement>) {
    return <p style={{ margin: "0.4em 0" }}>{children}</p>;
  },
  ul({ children }: React.HTMLAttributes<HTMLUListElement>) {
    return <ul style={{ margin: "0.3em 0", paddingLeft: "1.5em" }}>{children}</ul>;
  },
  ol({ children }: React.HTMLAttributes<HTMLOListElement>) {
    return <ol style={{ margin: "0.3em 0", paddingLeft: "1.5em" }}>{children}</ol>;
  },
  table({ children }: React.HTMLAttributes<HTMLTableElement>) {
    return (
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", width: "100%" }}>{children}</table>
      </div>
    );
  },
  th({ children }: React.ThHTMLAttributes<HTMLTableCellElement>) {
    return (
      <th style={{ border: "1px solid #444", padding: "6px 10px", background: "#2a2a2a" }}>
        {children}
      </th>
    );
  },
  td({ children }: React.TdHTMLAttributes<HTMLTableCellElement>) {
    return <td style={{ border: "1px solid #444", padding: "6px 10px" }}>{children}</td>;
  },
  a({ href, children }: React.AnchorHTMLAttributes<HTMLAnchorElement>) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    );
  },
  div({ className, style, children }: React.HTMLAttributes<HTMLDivElement>) {
    return <div className={className} style={style}>{children}</div>;
  },
  span({ className, style, children }: React.HTMLAttributes<HTMLSpanElement>) {
    return <span className={className} style={style}>{children}</span>;
  },
  button({ className, style, type, onClick, disabled, children }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
    return <button className={className} style={style} type={type} onClick={onClick} disabled={disabled}>{children}</button>;
  },
  style({ children }: React.StyleHTMLAttributes<HTMLStyleElement>) {
    return <style>{children}</style>;
  },
  details({ className, style, children }: React.DetailsHTMLAttributes<HTMLDetailsElement>) {
    return <details className={className} style={style}>{children}</details>;
  },
  summary({ className, style, children }: React.HTMLAttributes<HTMLElement>) {
    return <summary className={className} style={style}>{children}</summary>;
  },
  progress({ className, style, value, max, children }: React.ProgressHTMLAttributes<HTMLProgressElement>) {
    return <progress className={className} style={style} value={value} max={max}>{children}</progress>;
  },
  meter({ className, style, value, min, max, low, high, optimum, children }: React.MeterHTMLAttributes<HTMLMeterElement>) {
    return <meter className={className} style={style} value={value} min={min} max={max} low={low} high={high} optimum={optimum}>{children}</meter>;
  },
};

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

  const mdComponents = useMemo(
    () => ({
      ...markdownComponentsBase,
      code({ inline, className, children, ...props }: React.HTMLAttributes<HTMLElement> & { inline?: boolean }) {
        const match = /language-(\w+)/.exec(className || "");
        const code = String(children).replace(/\n$/, "");
        if (!inline && match) {
          if (match[1] === "mermaid") {
            if (streaming) {
              return <CodeBlock language="mermaid" code={code} />;
            }
            return <MermaidRenderer definition={code} />;
          }
          return <CodeBlock language={match[1]} code={code} />;
        }
        return (
          <code className={className} {...props}>
            {children}
          </code>
        );
      },
      img({ src, alt }: React.ImgHTMLAttributes<HTMLImageElement>) {
        return (
          <a href="#" onClick={(e) => { e.preventDefault(); onImageClick(src!); }} className="message-img-link">
            <img src={src} alt={alt || ""} className="message-img" />
          </a>
        );
      },
    }),
    [onImageClick, streaming]
  );

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
    return (
      <>
        {m.reasoningContent && (
          <details className="reasoning-block">
            <summary className="reasoning-summary">{reasoningLabel}</summary>
            <div className="reasoning-content">{m.reasoningContent}</div>
          </details>
        )}
        {typeof m.content === "string" ? (
          needsSandbox(textContent) ? (
            <SafeHtml html={textContent} />
          ) : (
            <ReactMarkdown
              remarkPlugins={[remarkGfm, remarkBreaks]}
              rehypePlugins={[rehypeRaw]}
              components={mdComponents}
            >
              {textContent || ""}
            </ReactMarkdown>
          )
        ) : (
          renderBlocksContent(m.content, m.role, m.id, onImageClick)
        )}
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

  return renderBlocksContent(m.content, m.role, m.id, onImageClick);
}

export { renderBlocksContent };