import type { JSX } from "react";
import DiffBlock from "./DiffBlock";

// 逻辑路径 "ws:uploads/test.png" → "/files/ws/uploads/test.png"
function toFileUrl(logicalPath: string): string | null {
  const colonIdx = logicalPath.indexOf(":");
  if (colonIdx < 0) return null;
  const ns = logicalPath.slice(0, colonIdx);
  const rest = logicalPath.slice(colonIdx + 1).replace(/^\/+/, "");
  return `/files/${ns}/${rest}`;
}

// 去除行号前缀: "1: hello\n2: world" → "hello\nworld"
function stripLineNumbers(content: string): string {
  return content.replace(/^\d+: /gm, "");
}

type RenderFn = (
  parsed: Record<string, unknown>,
  onImageClick: (src: string) => void,
) => JSX.Element | null;

// Read 工具特化渲染：用 DiffBlock plain 模式（无颜色、无前缀，仅行号+内容）
const renderRead: RenderFn = (parsed, onImageClick) => {
  if (parsed.type === "file" && typeof parsed.content === "string") {
    const code = stripLineNumbers(parsed.content);
    const offset = typeof parsed.offset === "number" ? parsed.offset : 0;
    return <DiffBlock oldText="" newText={code} startLine={offset + 1} plain />;
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

// PatchEdit 工具特化渲染：diffs 字段为 [[old_text, new_text, start_line], ...]，每个三元组渲染一个 DiffBlock
const renderPatchEdit: RenderFn = (parsed) => {
  const diffs = parsed.diffs;
  if (!Array.isArray(diffs) || diffs.length === 0) return null;
  const triples: [string, string, number][] = [];
  for (const d of diffs) {
    if (Array.isArray(d) && d.length >= 2 && typeof d[0] === "string" && typeof d[1] === "string") {
      const startLine = typeof d[2] === "number" ? d[2] : 1;
      triples.push([d[0], d[1], startLine]);
    }
  }
  if (triples.length === 0) return null;
  return (
    <div className="diff-block-list">
      {triples.map((t, i) => (
        <DiffBlock key={i} oldText={t[0]} newText={t[1]} startLine={t[2]} />
      ))}
    </div>
  );
};

// 注册表：toolName → 特化渲染函数（精确匹配优先）
const registry: Record<string, RenderFn> = {
  Read: renderRead,
  PatchEdit: renderPatchEdit,
};

// 所有渲染器列表，用于 toolName 缺失时的结构匹配 fallback
const allRenderers: RenderFn[] = [renderRead, renderPatchEdit];

// 对外接口：toolName 精确匹配优先，缺失或未命中时按结构特征逐个尝试
export function renderToolResult(
  toolName: string | undefined,
  parsed: Record<string, unknown>,
  onImageClick: (src: string) => void,
): JSX.Element | null {
  // 优先按 toolName 精确匹配
  if (toolName) {
    const renderer = registry[toolName];
    if (renderer) {
      const result = renderer(parsed, onImageClick);
      if (result) return result;
    }
  }
  // toolName 缺失或未命中注册表：按结构特征逐个尝试
  for (const renderer of allRenderers) {
    const result = renderer(parsed, onImageClick);
    if (result) return result;
  }
  return null;
}