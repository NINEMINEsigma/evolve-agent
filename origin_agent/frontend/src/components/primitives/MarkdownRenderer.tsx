import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import remarkBreaks from "remark-breaks";
import rehypeRaw from "rehype-raw";
import rehypeKatex from "rehype-katex";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import "katex/dist/katex.min.css";
import type { Components } from "react-markdown";
import CodeBlock from "../CodeBlock";
import SafeHtml from "../SafeHtml";
import IframeRenderer from "../IframeRenderer";
import MermaidRenderer from "../MermaidRenderer";
import { normalizeMarkdownMathDelimiters } from "../../utils/markdownMath";
import { useMessageRenderEnvironment } from "./MessageRenderEnvironment";

// 当文本包含 script、style、link 等标签时，需要完整隔离渲染，避免 CSS/JS 污染外层页面
// iframe 不在此列——<iframe src="url"> 本身就是浏览器沙盒，走 ReactMarkdown 管线即可
const SANDBOX_TAG_RE = /<script\b|<style\b|<link\b|<object\b|<embed\b/i;

// 离线原始 HTML 净化白名单：默认 GitHub schema 之上明确拒绝 iframe 等可主动加载节点。
const OFFLINE_SANITIZE_SCHEMA = {
  ...defaultSchema,
  tagNames: [...(defaultSchema.tagNames ?? []).filter(
    (tag) => !["iframe", "script", "style", "link", "meta", "base", "form", "object", "embed"].includes(tag),
  ), "audio", "video", "source"],
  attributes: {
    ...defaultSchema.attributes,
    audio: ["src", "controls", "preload"], video: ["src", "poster", "controls", "preload"], source: ["src", "type"],
  },
  protocols: { ...defaultSchema.protocols, src: ["http", "https", "data", "blob", "export-asset"] },
};

// 剥离围栏代码块和行内代码内容后检测，避免代码中的标签字面量触发误判
function stripCodeForDetection(text: string): string {
  return text
    .replace(/(`{3,}|~{3,})[^\n]*\n[\s\S]*?\1/g, "")  // 围栏代码块
    .replace(/`+[^`\n]*?`+/g, "");                      // 行内代码
}

function needsSandbox(text: string): boolean {
  return SANDBOX_TAG_RE.test(stripCodeForDetection(text));
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
  iframe(props: React.IframeHTMLAttributes<HTMLIFrameElement>) {
    return <IframeRenderer {...props} />;
  },
};

interface MarkdownRendererProps {
  content: string;
  streaming?: boolean;
  onImageClick?: (src: string) => void;
}

export default function MarkdownRenderer({ content, streaming, onImageClick }: MarkdownRendererProps) {
  const environment = useMessageRenderEnvironment();
  const offline = environment.mode === "offline";
  const normalizedContent = useMemo(
    () => normalizeMarkdownMathDelimiters(content),
    [content]
  );

  const handleMermaidError = useMemo(() => {
    if (!offline) return undefined;
    return (message: string) => environment.reportIssue?.("mermaid_render_failed", message);
  }, [environment, offline]);

  const renderMermaidFallback = useMemo(() => {
    if (!offline) return undefined;
    return (message: string, definition: string) => (
      <div className="mermaid-offline-fallback">
        <div className="mermaid-offline-warning">
          {environment.labels?.diagramFailed ?? "Diagram cannot be rendered offline; original definition shown below."}
        </div>
        <pre className="mermaid-source">{definition}</pre>
        {message && <div className="mermaid-offline-detail">{message}</div>}
      </div>
    );
  }, [environment, offline]);

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
            return (
              <MermaidRenderer
                definition={code}
                sanitizeSvg={environment.sanitizeSvg}
                onRenderError={offline ? handleMermaidError : undefined}
                errorFallback={offline ? renderMermaidFallback : undefined}
              />
            );
          }
          return <CodeBlock language={match[1]} code={code} onCopyFailure={environment.onCopyFailure} />;
        }
        return (
          <code className={className} {...props}>
            {children}
          </code>
        );
      },
      img({ src, alt }: React.ImgHTMLAttributes<HTMLImageElement>) {
        const resolved = src ? environment.resolveResource(src, "image") : null;
        // live: resolve 原样返回；offline: 未归档返回 null → 显示占位，绝不保留在线依赖。
        if (src && resolved == null) {
          return (
            <span className="offline-resource-placeholder" data-offline-resource="image">
              {environment.labels?.resourceUnavailable ?? "resource unavailable offline"}
            </span>
          );
        }
        const shown = resolved ?? src ?? "";
        return (
          <a href="#" onClick={(e) => { e.preventDefault(); onImageClick && onImageClick(shown); }} className="message-img-link">
            <img src={shown} alt={alt || ""} className="message-img" />
          </a>
        );
      },
      a({ href, children }: React.AnchorHTMLAttributes<HTMLAnchorElement>) {
        if (offline) return <span>{children}{href && <small className="offline-link-url"> ({href})</small>}</span>;
        return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
      },
      audio({ src, children, ...props }: React.AudioHTMLAttributes<HTMLAudioElement>) {
        if (!offline) return <audio {...props} src={src}>{children}</audio>;
        const local = src ? environment.resolveResource(src, "audio") : null;
        return src && !local ? <span>{environment.labels?.resourceUnavailable}</span> : <audio src={local || undefined} controls preload="metadata">{children}</audio>;
      },
      video({ src, poster, children, ...props }: React.VideoHTMLAttributes<HTMLVideoElement>) {
        if (!offline) return <video {...props} src={src} poster={poster}>{children}</video>;
        const local = src ? environment.resolveResource(src, "video") : null;
        const preview = poster ? environment.resolveResource(poster, "image") : null;
        return src && !local ? <span>{environment.labels?.resourceUnavailable}</span> : <video src={local || undefined} poster={preview || undefined} controls preload="metadata">{children}</video>;
      },
      source({ src, type, ...props }: React.SourceHTMLAttributes<HTMLSourceElement>) {
        if (!offline) return <source {...props} src={src} type={type} />;
        const local = src ? environment.resolveResource(src, "video") : null;
        return local ? <source src={local} type={type} /> : null;
      },
      iframe(props: React.IframeHTMLAttributes<HTMLIFrameElement>) {
        if (offline) {
          return environment.renderIframe(props.src ?? "");
        }
        return <IframeRenderer {...props} />;
      },
    }),
    [environment, offline, onImageClick, streaming]
  );

  if (needsSandbox(normalizedContent)) {
    if (offline) {
      return <>{environment.renderHtml(normalizedContent)}</>;
    }
    return <SafeHtml html={normalizedContent} />;
  }

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, [remarkMath, { singleDollarTextMath: true }], remarkBreaks]}
      rehypePlugins={offline
        ? [rehypeRaw, [rehypeSanitize, OFFLINE_SANITIZE_SCHEMA], [rehypeKatex, { throwOnError: false }]]
        : [rehypeRaw, [rehypeKatex, { throwOnError: false }]]}
      urlTransform={offline ? (url) => url : undefined}
      components={mdComponents}
    >
      {normalizedContent || ""}
    </ReactMarkdown>
  );
}