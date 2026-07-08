import { useMemo } from "react";

/**
 * 在 assistant 消息气泡中安全渲染 AI 输出的静态 HTML。
 *
 * 规则：
 * - 只保留展示性标签；
 * - 删除 script/iframe/object/embed/form 等可执行/可交互标签；
 * - 删除所有 on* 事件属性和危险 URL 协议；
 * - 过滤可能破坏全局布局的 CSS。
 */

const BLOCKED_TAGS = new Set([
  "script",
  "style",
  "iframe",
  "object",
  "embed",
  "form",
  "input",
  "textarea",
  "button",
  "select",
  "option",
  "optgroup",
  "link",
  "meta",
  "base",
  "template",
  "dialog",
  "canvas",
  "audio",
  "video",
  "source",
  "track",
  "map",
  "area",
]);

const DANGEROUS_PROTOCOLS = ["javascript:", "data:", "vbscript:"];

// 过滤可能破坏页面整体布局或造成覆盖遮罩的样式声明
const DANGEROUS_CSS_RE =
  /position\s*:\s*(fixed|absolute|sticky)|\bwidth\s*:\s*100vw\b|\bheight\s*:\s*100vh\b|left\s*:\s*-?\d|top\s*:\s*-?\d|z-index\s*:\s*\d{4,}/gi;

function isDangerousUrl(value: string): boolean {
  const trimmed = value.trim().toLowerCase();
  return DANGEROUS_PROTOCOLS.some((p) => trimmed.startsWith(p));
}

function sanitizeStyle(style: string): string | undefined {
  const cleaned = style
    .split(";")
    .map((rule) => rule.trim())
    .filter((rule) => rule && !DANGEROUS_CSS_RE.test(rule.toLowerCase()))
    .join("; ");
  return cleaned || undefined;
}

function cleanElement(el: Element) {
  const tagName = el.tagName.toLowerCase();
  if (BLOCKED_TAGS.has(tagName)) {
    el.remove();
    return;
  }

  const attrs = Array.from(el.attributes);
  for (const attr of attrs) {
    const name = attr.name.toLowerCase();
    const value = attr.value;

    if (name.startsWith("on")) {
      el.removeAttribute(attr.name);
      continue;
    }

    if (name === "srcdoc") {
      el.removeAttribute(attr.name);
      continue;
    }

    if (name === "action" && tagName === "form") {
      el.removeAttribute(attr.name);
      continue;
    }

    if ((name === "href" || name === "src" || name === "poster") && isDangerousUrl(value)) {
      el.removeAttribute(attr.name);
      continue;
    }

    if (name === "style") {
      const cleaned = sanitizeStyle(value);
      if (cleaned) {
        el.setAttribute("style", cleaned);
      } else {
        el.removeAttribute(attr.name);
      }
      continue;
    }
  }

  // 递归清理子节点（从后向前删除更安全）
  const children = Array.from(el.children);
  for (const child of children) {
    cleanElement(child);
  }
}

function sanitizeHtml(html: string): string {
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, "text/html");
  const body = doc.body;

  // body 本身不需要检查 tagName，直接清理它的子元素
  const children = Array.from(body.children);
  for (const child of children) {
    cleanElement(child);
  }

  return body.innerHTML;
}

interface SafeHtmlProps {
  html: string;
  className?: string;
}

export default function SafeHtml({ html, className }: SafeHtmlProps) {
  const sanitized = useMemo(() => sanitizeHtml(html), [html]);
  return (
    <div
      className={className}
      dangerouslySetInnerHTML={{ __html: sanitized }}
    />
  );
}