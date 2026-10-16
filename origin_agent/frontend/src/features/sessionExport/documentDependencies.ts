import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { visit } from "unist-util-visit";
import postcss from "postcss";
import valueParser from "postcss-value-parser";
import type { HistoryContentRowDto } from "../chat/types";
import type { ExportDependency, ExportDependencyScan, ExportDocumentKind } from "./types";
import { record } from "./api";
import { extractScriptDependencies } from "./scriptDependencies";

export function sourceFileUrl(logical: string, origin: string): string {
  const split = logical.indexOf(":");
  if (split < 1) throw new Error("Invalid logical export resource");
  const ns = encodeURIComponent(logical.slice(0, split));
  const path = logical.slice(split + 1).split("/").map(encodeURIComponent).join("/");
  return new URL(`/files/${ns}/${path}`, origin).href;
}
export function parseExportSrcset(value: string): string[] {
  const result: string[] = [];
  let at = 0;
  while (at < value.length) {
    while (/[\s,]/.test(value[at] || "") && at < value.length) at += 1;
    const start = at;
    const inline = value.slice(start, start + 5).toLowerCase() === "data:";
    while (at < value.length && !/\s/.test(value[at]) && (inline || value[at] !== ",")) at += 1;
    let url = value.slice(start, at);
    const ended = url.endsWith(",") || value[at] === ",";
    if (value[at] === ",") at += 1;
    url = url.replace(/,+$/, "");
    if (url) result.push(url);
    if (!ended) while (at < value.length && value[at++] !== ",") { /* 跳过像素密度描述。 */ }
  }
  return result;
}
export function extractDocumentDependencies(source: string, baseUrl: string, kind: ExportDocumentKind): ExportDependencyScan {
  const dependencies: ExportDependency[] = [];
  const issues: ExportDependencyScan["issues"] = [];
  const add = (url: string, type: ExportDocumentKind = "media") => {
    if (url && !url.startsWith("#")) dependencies.push({ url, baseUrl, kind: type, owner: baseUrl, depth: 0 });
  };
  const css = (text: string) => {
    try {
      const tree = postcss.parse(text);
      tree.walkDecls((decl) => {
        valueParser(decl.value).walk((node) => {
          if (node.type !== "function") return;
          if (node.value.toLowerCase() === "url") {
            const value = node.nodes.find((part) => part.type === "word" || part.type === "string");
            if (value) add(value.value);
          } else if (["image-set", "-webkit-image-set"].includes(node.value.toLowerCase())) {
            for (const child of node.nodes) if (child.type === "string") add(child.value);
          }
        });
      });
      tree.walkAtRules("import", (rule) => {
        const parsed = valueParser(rule.params);
        const first = parsed.nodes[0];
        if (first?.type === "string") add(first.value, "css");
        else if (first?.type === "function" && first.value.toLowerCase() === "url") {
          const value = first.nodes.find((node) => node.type === "word" || node.type === "string");
          if (value) add(value.value, "css");
        }
      });
    } catch { issues.push({ owner: baseUrl, source: baseUrl, code: "invalid_css" }); }
  };
  if (kind === "css") css(source);
  else if (kind === "script") return extractScriptDependencies(source, baseUrl);
  else if (kind === "json") {
    try {
      const data = record(JSON.parse(source));
      if (data.meta && typeof data.meta === "object") {
        const meta = record(data.meta);
        if (typeof meta.image === "string") add(meta.image);
      }
    } catch { /* 非图集二进制/JSON不猜测其他字符串的资源含义。 */ }
  } else if (kind === "html") {
    // template 内容始终惰性，不把 DOMParser 解析后可能加载的 img/iframe 插入页面。
    const template = document.createElement("template");
    template.innerHTML = source;
    for (const element of template.content.querySelectorAll("*")) {
      if (element.hasAttribute("style")) css(element.getAttribute("style") || "");
      const tag = element.tagName.toLowerCase();
      if (tag === "style") css(element.textContent || "");
      if (["img", "audio", "video", "source"].includes(tag)) {
        add(element.getAttribute("src") || "");
        if (tag === "video") add(element.getAttribute("poster") || "");
        for (const url of parseExportSrcset(element.getAttribute("srcset") || "")) add(url);
      }
      if (tag === "link" && element.getAttribute("rel")?.toLowerCase() === "stylesheet") add(element.getAttribute("href") || "", "css");
      if (tag === "script") {
        if (element.getAttribute("type") === "module") issues.push({ owner: baseUrl, source: baseUrl, code: "unsupported_module" });
        else if (element.hasAttribute("src")) add(element.getAttribute("src") || "", "script");
        else {
          const scan = extractScriptDependencies(element.textContent || "", baseUrl);
          dependencies.push(...scan.dependencies); issues.push(...scan.issues);
        }
      }
      if (["iframe", "object", "embed"].includes(tag)) issues.push({ owner: baseUrl, source: element.getAttribute("src") || baseUrl, code: "unsupported_embedded_document" });
    }
  }
  return { dependencies, issues };
}
export function extractMarkdownDependencies(text: string, baseUrl: string, owner: string): ExportDependencyScan {
  const tree = unified().use(remarkParse).use(remarkGfm).use(remarkMath).parse(text);
  const dependencies: ExportDependency[] = [];
  const issues: ExportDependencyScan["issues"] = [];
  const definitions = new Map<string, string>();
  visit(tree, (node) => {
    const value = record(node);
    if (node.type === "definition" && typeof value.identifier === "string" && typeof value.url === "string") definitions.set(value.identifier.toLowerCase(), value.url);
  });
  visit(tree, (node) => {
    const value = record(node);
    const url = node.type === "image" && typeof value.url === "string" ? value.url
      : node.type === "imageReference" && typeof value.identifier === "string" ? definitions.get(value.identifier.toLowerCase()) : null;
    if (url) dependencies.push({ url, baseUrl, owner, kind: "media", depth: 0 });
    if (node.type === "html" && typeof value.value === "string") {
      const scan = extractDocumentDependencies(value.value, baseUrl, "html");
      dependencies.push(...scan.dependencies.map((dependency) => ({ ...dependency, owner })));
      issues.push(...scan.issues.map((issue) => ({ ...issue, owner })));
    }
  });
  return { dependencies, issues };
}
export function extractMessageDependencies(rows: readonly HistoryContentRowDto[], baseUrl = window.location.href): ExportDependencyScan {
  const dependencies: ExportDependency[] = [];
  const issues: ExportDependencyScan["issues"] = [];
  const add = (url: string, owner: string) => dependencies.push({ url, baseUrl, owner, kind: "media", depth: 0 });
  const scanContent = (content: unknown, owner: string, tool = false) => {
    if (Array.isArray(content)) {
      for (const raw of content) {
        const block = record(raw);
        if (block.type === "image_url") add(String(record(block.image_url).url), owner);
        if (block.type === "video_url") add(String(record(block.video_url).url), owner);
        if (block.type === "input_audio") {
          const audio = record(block.input_audio);
          const value = String(audio.data);
          add(value.startsWith("data:") || value.startsWith("export-asset:") ? value : `data:audio/${audio.format};base64,${value}`, owner);
        }
        if (block.type === "text" && typeof block.text === "string") {
          const scan = extractMarkdownDependencies(block.text, baseUrl, owner);
          dependencies.push(...scan.dependencies); issues.push(...scan.issues);
        }
      }
      return;
    }
    if (typeof content !== "string") return;
    if (tool) {
      let raw: unknown;
      try { raw = JSON.parse(content); } catch { return; }
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) return;
      const data = record(raw);
      if (typeof data.markdown === "string") {
        const scan = extractMarkdownDependencies(data.markdown, baseUrl, owner);
        dependencies.push(...scan.dependencies); issues.push(...scan.issues);
      }
      if (["image", "video", "audio"].includes(String(data.type)) && typeof data.path === "string") add(sourceFileUrl(data.path, baseUrl), owner);
      if (typeof data.download_url === "string") {
        if (["image", "video", "audio"].includes(String(data.type))) add(data.download_url, owner);
        else issues.push({ owner, source: data.download_url, code: "attachment_not_in_scope" });
      }
    } else {
      const scan = extractMarkdownDependencies(content, baseUrl, owner);
      dependencies.push(...scan.dependencies); issues.push(...scan.issues);
    }
  };
  for (const row of rows) {
    if (row.tool_card) {
      scanContent(row.tool_card.result_content, row.row_id, true);
      for (const embedded of row.tool_card.embedded_messages || []) scanContent(embedded.content, row.row_id);
    } else scanContent(row.content, row.row_id, row.role === "tool");
  }
  return { dependencies, issues };
}
