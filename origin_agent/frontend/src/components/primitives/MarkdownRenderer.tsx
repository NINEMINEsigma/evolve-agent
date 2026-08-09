import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import rehypeRaw from "rehype-raw";
import type { Components } from "react-markdown";
import CodeBlock from "../CodeBlock";
import SafeHtml from "../SafeHtml";
import IframeRenderer from "../IframeRenderer";
import MermaidRenderer from "../MermaidRenderer";

// 当文本包含 script、style、link 等标签时，需要完整隔离渲染，避免 CSS/JS 污染外层页面
// iframe 不在此列——<iframe src="url"> 本身就是浏览器沙盒，走 ReactMarkdown 管线即可
const SANDBOX_TAG_RE = /<script\b|<style\b|<link\b|<object\b|<embed\b/i;

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
          <a href="#" onClick={(e) => { e.preventDefault(); onImageClick && onImageClick(src!); }} className="message-img-link">
            <img src={src} alt={alt || ""} className="message-img" />
          </a>
        );
      },
    }),
    [onImageClick, streaming]
  );

  if (needsSandbox(content)) {
    return <SafeHtml html={content} />;
  }

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkBreaks]}
      rehypePlugins={[rehypeRaw]}
      components={mdComponents}
    >
      {content || ""}
    </ReactMarkdown>
  );
}