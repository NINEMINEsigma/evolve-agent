import type { JSX } from "react";
import CodeBlock from "./CodeBlock";

// 扩展名 → 语法高亮语言映射
const EXT_LANG_MAP: Record<string, string> = {
  py: "python", js: "javascript", jsx: "javascript",
  ts: "typescript", tsx: "typescript", json: "json",
  html: "html", css: "css", scss: "scss", less: "less",
  md: "markdown", yml: "yaml", yaml: "yaml", xml: "xml",
  sh: "bash", bat: "batch", ps1: "powershell",
  c: "c", h: "c", cpp: "cpp", hpp: "cpp", cc: "cpp",
  java: "java", go: "go", rs: "rust", rb: "ruby",
  php: "php", swift: "swift", kt: "kotlin",
  sql: "sql", toml: "toml", ini: "ini", cfg: "ini",
  conf: "ini", txt: "text", vue: "vue", svelte: "svelte",
};

function inferLanguage(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  return EXT_LANG_MAP[ext] ?? "text";
}

// 去除行号前缀: "1: hello\n2: world" → "hello\nworld"
function stripLineNumbers(content: string): string {
  return content.replace(/^\d+: /gm, "");
}

// 逻辑路径 "ws:uploads/test.png" → "/files/ws/uploads/test.png"
function toFileUrl(logicalPath: string): string | null {
  const colonIdx = logicalPath.indexOf(":");
  if (colonIdx < 0) return null;
  const ns = logicalPath.slice(0, colonIdx);
  const rest = logicalPath.slice(colonIdx + 1).replace(/^\/+/, "");
  return `/files/${ns}/${rest}`;
}

type RenderFn = (
  parsed: Record<string, unknown>,
  onImageClick: (src: string) => void,
) => JSX.Element | null;

// Read 工具特化渲染
const renderRead: RenderFn = (parsed, onImageClick) => {
  if (parsed.type === "file" && typeof parsed.content === "string") {
    const lang = inferLanguage(String(parsed.path ?? ""));
    const code = stripLineNumbers(parsed.content);
    return <CodeBlock language={lang} code={code} />;
  }
  if (parsed.type === "image" && typeof parsed.path === "string") {
    const url = toFileUrl(parsed.path);
    if (url) {
      return (
        <a href="#" onClick={(e) => { e.preventDefault(); onImageClick(url); }} className="message-img-link">
          <img src={url} alt={String(parsed.path ?? "")} className="message-img-thumb" />
        </a>
      );
    }
  }
  // directory → 默认 JsonView 足够清晰
  return null;
};

// 注册表：toolName → 特化渲染函数
const registry: Record<string, RenderFn> = {
  Read: renderRead,
};

// 对外接口：命中返回特化元素，未命中返回 null（调用方走默认 JsonView）
export function renderToolResult(
  toolName: string | undefined,
  parsed: Record<string, unknown>,
  onImageClick: (src: string) => void,
): JSX.Element | null {
  if (!toolName) return null;
  const renderer = registry[toolName];
  return renderer ? renderer(parsed, onImageClick) : null;
}