/**
 * 离线隔离 frame 运行期。
 *
 * 两件事：
 * 1. buildOfflineFrame：在内存 DOM 中净化用户 HTML 文档（移除 meta refresh/base/
 *    prefetch/外部 frame/表单/危险导航及不支持的加载方式），把静态引用改写为
 *    frame 本地 `export-asset:<id>` 引用，并把 frame 真正依赖的资源子表与转义后的
 *    bootstrap 参数一并写入固定顺序的文档骨架（charset、CSP meta、reset style、
 *    可信 bootstrap、用户 head/body）。frame 只携带自己的子表，不复制全会话资产。
 * 2. installOfflineResourceRuntime：作为字符串注入 frame 内，最先安装表内 fetch /
 *    通信入口禁用 / 异常报告，再创建 Blob URL 并按序注入经典脚本。
 *
 * 该文件不导入 chatRuntimeStore / App / useWebSocket / Monaco。
 */

import { EXPORT_FRAME_CSP } from "../limits";
import type { OfflineFrameAsset, OfflineFramePayload } from "./resourceRuntime";
import { canonicalizeExportRef, offlineAssetText } from "./resourceRuntime";
import { extractScriptDependencies, rewriteScriptResources } from "../scriptDependencies";
import { parseExportSrcset } from "../documentDependencies";
import postcss from "postcss";
import valueParser from "postcss-value-parser";

/** frame 内资源运行期的源码字符串（注入为经典脚本，运行在 opaque origin）。 */
const FRAME_RUNTIME_SOURCE = String.raw`
(function () {
  var payload = window.__OFFLINE_FRAME__;
  if (!payload) return;
  var nonce = payload.nonce;
  function report(code, detail) {
    try {
      if (window.parent && window.parent !== window) {
        window.parent.postMessage({ type: "offline-frame-issue", nonce: nonce, code: String(code), detail: String(detail || "").slice(0, 500) }, "*");
      }
    } catch (e) { /* opaque origin postMessage 忽略失败 */ }
  }
  var baseUrl = payload.baseUrl || document.baseURI;
  var byId = Object.create(null);
  var aliases = payload.aliases || Object.create(null);
  var urls = Object.create(null);
  (payload.assets || []).forEach(function (asset) { byId[asset.id] = asset; });
  function bytesOf(base64) {
    var binary = atob(base64);
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return bytes;
  }
  function blobUrl(id) {
    if (urls[id]) return urls[id];
    var asset = byId[id];
    if (!asset) return null;
    var url = URL.createObjectURL(new Blob([bytesOf(asset.base64)], { type: asset.mime || "application/octet-stream" }));
    urls[id] = url;
    return url;
  }
  function idFor(raw) {
    var value = String(raw == null ? "" : raw).trim();
    if (!value) return null;
    var key = value;
    if (value.indexOf("export-asset:") === 0) {
      var bare = value.slice("export-asset:".length);
      return byId[bare] ? bare : null;
    }
    if (aliases[key]) return aliases[key];
    var existing = Object.keys(urls);
    for (var n = 0; n < existing.length; n++) if (urls[existing[n]] === value) return existing[n];
    try {
      var parsed = new URL(value, baseUrl);
      parsed.hash = "";
      ["visual_raw", "visual_probe", "visual_sid", "visual_kind"].forEach(function (name) { parsed.searchParams.delete(name); });
      key = parsed.href;
    } catch (e) { key = value; }
    return aliases[key] || null;
  }
  function localUrl(raw) {
    var id = idFor(raw);
    return id ? blobUrl(id) : null;
  }
  // 表内 fetch 适配：解析为本地 bytes，命中返回 Response，未命中明确失败，绝不回落网络。
  var scriptsAllowed = true;
  function lockCapability(target, name, value) {
    try { Object.defineProperty(target, name, { value: value, configurable: false, writable: false }); }
    catch (error) { scriptsAllowed = false; report("unsupported_script_capability", name); }
  }
  lockCapability(window, "fetch", function (input, init) {
    var raw = (input && typeof input === "object" && "url" in input) ? input.url : String(input);
    var method = (init && init.method) || (input && input.method) || "GET";
    if (String(method).toUpperCase() !== "GET" || (init && init.body)) {
      report("offline_fetch_unmatched", "Only local GET is supported");
      return Promise.reject(new Error("Unsupported offline request"));
    }
    var id = idFor(raw);
    if (!id) {
      report("offline_fetch_unmatched", raw);
      return Promise.reject(new Error("offline resource not available: " + raw));
    }
    var asset = byId[id];
    var content = bytesOf(asset.base64);
    if (/json/i.test(asset.mime) || /\.json(?:[?#]|$)/i.test(raw)) {
      try {
        var object = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(content));
        if (object && object.meta && typeof object.meta.image === 'string') {
          var atlasUrl = new URL(object.meta.image, new URL(raw, baseUrl)).href;
          var imageUrl = localUrl(atlasUrl);
          if (imageUrl) { object.meta.image = imageUrl; content = new TextEncoder().encode(JSON.stringify(object)); }
          else report('offline_asset_missing', atlasUrl);
        }
      } catch (error) { report('offline_json_unavailable', raw); }
    }
    return Promise.resolve(new Response(content, { status: 200, headers: { "Content-Type": asset.mime || "application/octet-stream" } }));
  });
  function disable(name) {
    if (!(name in window)) return;
    lockCapability(window, name, function () { report("offline_comm_disabled", name); throw new Error(name + " disabled in offline export"); });
  }
  ["XMLHttpRequest", "WebSocket", "EventSource", "Worker", "SharedWorker", "WebTransport", "RTCPeerConnection", "webkitRTCPeerConnection"].forEach(disable);
  if ("sendBeacon" in navigator) lockCapability(navigator, "sendBeacon", function () { report("offline_comm_disabled", "sendBeacon"); return false; });
  if ("serviceWorker" in navigator) lockCapability(navigator, "serviceWorker", undefined);
  window.addEventListener("error", function (event) {
    report("offline_runtime_error", (event && event.message) || "error");
  });
  window.addEventListener("unhandledrejection", function (event) {
    report("offline_unhandled_rejection", (event && event.reason && event.reason.message) || "rejection");
  });
  window.addEventListener("securitypolicyviolation", function (event) {
    report("offline_csp_violation", (event && event.violatedDirective) || "csp");
  });
  // 按原始次序注入经典脚本：先内联脚本，再按 src 顺序加载本地 Blob。
  function injectScripts() {
    if (!scriptsAllowed) { report("unsupported_script_capability", "Runtime isolation unavailable; scripts were not run"); return; }
    var frameScripts = payload.scripts || [];
    function localizeScript(source) {
      return String(source || "").replace(/export-asset:asset-\d+/g, function (ref) { return localUrl(ref) || ref; });
    }
    var scriptSpecs = frameScripts;
    var index = 0;
    function step() {
      if (index >= scriptSpecs.length) {
        document.dispatchEvent(new Event('DOMContentLoaded'));
        return;
      }
      var spec = scriptSpecs[index++];
      var el = document.createElement("script");
      if (spec.src) {
        var url = localUrl(spec.src);
        if (!url) { report("offline_script_missing", spec.src); step(); return; }
        el.src = url;
        el.onload = step;
        el.onerror = function () { report("offline_script_error", spec.src); step(); };
        document.body.appendChild(el);
        return;
      }
      el.textContent = localizeScript(spec.code || "");
      document.body.appendChild(el);
      step();
    }
    step();
  }
  // DOM 引用本地化：把 export-asset:<id> 属性引用与本帧内联样式 url() 换成 Blob URL。
  function localizeAttr(el, name) {
    var value = el.getAttribute('data-offline-' + name);
    if (!value) return;
    var url = localUrl(value);
    if (url) el.setAttribute(name === 'xlink' ? 'xlink:href' : name, url);
    else report("offline_asset_missing", value);
  }
  function localizeDom() {
    var nodes = document.querySelectorAll("[data-offline-src],[data-offline-href],[data-offline-poster],[data-offline-background],[data-offline-xlink]");
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      localizeAttr(el, "src");
      localizeAttr(el, "href");
      localizeAttr(el, "poster");
      localizeAttr(el, "background");
      localizeAttr(el, "xlink");
    }
    var styled = document.querySelectorAll("[data-offline-style]");
    for (var j = 0; j < styled.length; j++) {
      var styleValue = styled[j].getAttribute("data-offline-style");
      if (styleValue) {
        styled[j].setAttribute("style", styleValue.replace(/export-asset:asset-\d+/g, function (ref) { return localUrl(ref) || 'data:,'; }));
      }
    }
    var styleSheets = document.querySelectorAll("style[data-offline-sheet]");
    for (var k = 0; k < styleSheets.length; k++) {
      var css = styleSheets[k].textContent || "";
      styleSheets[k].textContent = css.replace(/export-asset:asset-\d+/g, function (ref) { return localUrl(ref) || 'data:,'; });
      styleSheets[k].type = 'text/css';
    }
  }
  function start() {
    localizeDom();
    injectScripts();
    startHeightReporting();
  }
  function sendHeight() {
    try {
      var body = document.body;
      var height = body ? Math.max(body.scrollHeight, body.offsetHeight) : 0;
      if (window.parent && window.parent !== window) {
        window.parent.postMessage({ type: "offline-frame-resize", nonce: nonce, height: height }, "*");
      }
    } catch (e) { /* 忽略 */ }
  }
  function startHeightReporting() {
    sendHeight();
    if (typeof ResizeObserver !== "undefined") {
      try { new ResizeObserver(sendHeight).observe(document.body); } catch (e) { /* 忽略 */ }
    }
    window.addEventListener("load", sendHeight);
    window.addEventListener("resize", sendHeight);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
  window.addEventListener("pagehide", function () {
    Object.keys(urls).forEach(function (id) { try { URL.revokeObjectURL(urls[id]); } catch (e) { /* 忽略 */ } });
  });
})();
`;

export interface FrameScriptSpec {
  /** 内联脚本原文；与 src 互斥。 */
  code?: string;
  /** 经典脚本本地引用（export-asset: 或原入口 URL）。 */
  src?: string;
}

export interface BuildOfflineFrameInput {
  /** 原始 HTML 文档字符串。 */
  html: string;
  /** 该 frame 真正依赖的资源子表与别名。 */
  payload: OfflineFramePayload;
  /** 父页面为本次 frame 生成的一次性 nonce。 */
  nonce: string;
  /** 文档基地址（原入口 URL），用于相对引用解析。 */
  baseUrl: string;
  /** 运行期问题上报（父页面生成阶段已知的降级）。 */
  onIssue?: (code: string, detail: string) => void;
}

const REMOVED_TAGS = new Set([
  "base", "meta", "form", "object", "embed", "iframe", "frame", "frameset", "portal",
]);

function escapeInlineJson(value: unknown): string {
  return JSON.stringify(value)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}

function stripDangerous(doc: Document, onIssue?: (code: string, detail: string) => void): void {
  // meta refresh / CSP 冲突的 meta 全部移除；frame 自带固定 CSP。
  doc.querySelectorAll("meta").forEach((meta) => {
    if (meta.getAttribute("http-equiv")?.toLowerCase() === "refresh") {
      onIssue?.("frame_meta_refresh_removed", "meta refresh removed");
    }
    meta.remove();
  });
  // link 预取/预连接/外部样式之外的资源加载：保留 stylesheet（稍后本地化），移除其余。
  doc.querySelectorAll("link").forEach((link) => {
    const rel = (link.getAttribute("rel") || "").toLowerCase();
    if (rel === "stylesheet") return;
    if (/prefetch|preload|preconnect|dns-prefetch|modulepreload|manifest|icon/.test(rel)) {
      link.remove();
      onIssue?.("frame_link_removed", rel);
      return;
    }
    link.remove();
  });
  // 危险/不支持节点：base、form、外部 frame、对象嵌入等。
  doc.querySelectorAll("base, form, object, embed, iframe, frame, frameset, portal, noscript").forEach((node) => {
    const tag = node.tagName.toLowerCase();
    if (REMOVED_TAGS.has(tag) || tag === "noscript") {
      node.remove();
      onIssue?.("frame_node_removed", tag);
    }
  });
  doc.querySelectorAll("script").forEach((script) => {
    const src = script.getAttribute("src");
    const type = (script.getAttribute("type") || "").toLowerCase();
    if (type && type !== "text/javascript" && type !== "module" && type !== "application/javascript") {
      script.remove();
      return;
    }
    if (type === "module" || src && /\.mjs(\?|$)/i.test(src)) {
      script.remove();
      onIssue?.("frame_module_script_removed", src || "inline module");
      return;
    }
    if (script.hasAttribute("async") || script.hasAttribute("defer")) {
      onIssue?.("frame_script_async_flattened", src || "inline");
    }
  });
}

/** 从文档中按原始次序提取经典脚本规格。 */
function extractScripts(doc: Document): FrameScriptSpec[] {
  const specs: FrameScriptSpec[] = [];
  doc.querySelectorAll("script").forEach((script) => {
    const src = script.getAttribute("src");
    const type = (script.getAttribute("type") || "").toLowerCase();
    if (type && type !== "text/javascript" && type !== "application/javascript") return;
    if (src) {
      // 内联 src 需在后续阶段解析为本地引用；此处保留原始 src 值。
      specs.push({ src });
    } else {
      specs.push({ code: script.textContent || "" });
    }
    script.remove();
  });
  return specs;
}

/** 把节点中的静态资源引用改写为 export-asset: 本地引用（命中才改写）。 */
function rewriteRefs(root: ParentNode, resolve: (raw: string) => string | null, onIssue?: (code: string, detail: string) => void): void {
  root.querySelectorAll("*").forEach((element) => {
    for (const name of ["src", "poster", "background"]) {
      const raw = element.getAttribute(name);
      if (!raw) continue;
      element.removeAttribute(name);
      const local = resolve(raw);
      if (local) element.setAttribute(`data-offline-${name}`, local);
      else { element.setAttribute("data-offline-missing", "true"); onIssue?.("frame_resource_unresolved", raw); }
    }
    const srcset = element.getAttribute("srcset");
    if (srcset) {
      element.removeAttribute("srcset");
      const refs = parseExportSrcset(srcset).map(resolve);
      const local = refs.find((ref) => ref !== null);
      if (local && !element.hasAttribute("data-offline-src")) element.setAttribute("data-offline-src", local);
    }
    if (element.hasAttribute("style")) {
      try { element.setAttribute("style", rewriteCssRefs(element.getAttribute("style") || "", resolve)); }
      catch { element.removeAttribute("style"); onIssue?.("frame_style_invalid", "style"); }
    }
    if (["image", "use"].includes(element.tagName.toLowerCase())) {
      for (const name of ["href", "xlink:href"]) {
        const raw = element.getAttribute(name);
        if (!raw || raw.startsWith("#")) continue;
        element.removeAttribute(name);
        const local = resolve(raw);
        if (local) element.setAttribute(`data-offline-${name === "href" ? "href" : "xlink"}`, local);
      }
    }
  });
}

/** 用一个足够保守的 url() 重写处理内联样式/样式表文本。 */
export function rewriteCssRefs(css: string, resolve: (raw: string) => string | null): string {
  const tree = postcss.parse(css);
  tree.walkDecls((declaration) => {
    const parsed = valueParser(declaration.value);
    parsed.walk((node) => {
      if (node.type !== "function") return;
      if (node.value.toLowerCase() === "url") {
        const value = node.nodes.find((child) => child.type === "string" || child.type === "word");
        if (value && !value.value.startsWith("#")) {
          value.value = resolve(value.value) || "data:,";
          value.type = "string";
        }
      } else if (["image-set", "-webkit-image-set"].includes(node.value.toLowerCase())) {
        for (const child of node.nodes) if (child.type === "string") child.value = resolve(child.value) || "data:,";
      }
    });
    declaration.value = parsed.toString();
  });
  return tree.toString();
}

export interface BuiltOfflineFrame {
  /** 序列化后的 frame 文档字符串。 */
  html: string;
  /** 该 frame 依赖的资源子表（父页面据此登记清理）。 */
  payload: OfflineFramePayload;
}

/**
 * 构建隔离 frame 文档。返回序列化 HTML 与本 frame 子表。
 * 不在导出应用执行用户 HTML/JS；脚本仅交给 frame 内 bootstrap 运行。
 */
export function buildOfflineFrame(input: BuildOfflineFrameInput): BuiltOfflineFrame {
  const template = document.createElement("template");
  template.innerHTML = input.html;
  const doc = document.implementation.createHTMLDocument("");
  // 独立 inert 文档没有浏览上下文，原资源不会挂载到主页面。
  doc.body.appendChild(template.content);
  const resolveFrom = (raw: string, base: string): string | null => {
    const key = canonicalizeExportRef(raw, base);
    const id = input.payload.aliases[key];
    if (!id) { input.onIssue?.("frame_resource_unresolved", raw.slice(0, 500)); return null; }
    return `export-asset:${id}`;
  };
  const resolveInMemory = (raw: string): string | null => resolveFrom(raw, input.baseUrl);
  const assetFor = (ref: string) => input.payload.assets.find((asset) => `export-asset:${asset.id}` === ref);
  const localizeCss = (source: string, base: string, seen = new Set<string>(), depth = 0): string => {
    if (depth > 16) { input.onIssue?.("frame_css_depth_limit", base); return ""; }
    const tree = postcss.parse(source);
    tree.walkAtRules("import", (rule) => {
      const first = valueParser(rule.params).nodes[0];
      const token = first?.type === "string" ? first.value
        : first?.type === "function" ? first.nodes.find((node) => node.type === "word" || node.type === "string")?.value : undefined;
      const key = token ? canonicalizeExportRef(token, base) : "";
      const ref = token ? resolveFrom(token, base) : null;
      const asset = ref ? assetFor(ref) : null;
      if (!asset || seen.has(key)) { rule.remove(); input.onIssue?.("frame_css_import_unresolved", token || base); return; }
      const nextSeen = new Set(seen); nextSeen.add(key);
      const nested = localizeCss(offlineAssetText(asset), key, nextSeen, depth + 1);
      const suffix = rule.params.slice(first?.sourceEndIndex || 0).trim();
      if (suffix) {
        const media = postcss.atRule({ name: "media", params: suffix });
        media.append(postcss.parse(nested).nodes); rule.replaceWith(media);
      } else rule.replaceWith(...postcss.parse(nested).nodes);
    });
    return rewriteCssRefs(tree.toString(), (raw) => resolveFrom(raw, base));
  };

  stripDangerous(doc, input.onIssue);
  const scripts = extractScripts(doc);

  // head 样式本地化
  doc.querySelectorAll('link[rel="stylesheet"]').forEach((link) => {
    const href = link.getAttribute("href");
    const local = href ? resolveInMemory(href) : null;
    const asset = local ? assetFor(local) : null;
    if (!href || !asset) { link.remove(); input.onIssue?.("frame_stylesheet_unresolved", href || "stylesheet"); return; }
    const style = doc.createElement("style");
    try { style.textContent = localizeCss(offlineAssetText(asset), canonicalizeExportRef(href, input.baseUrl)); }
    catch { input.onIssue?.("frame_stylesheet_invalid", href); }
    link.replaceWith(style);
  });
  doc.querySelectorAll("style").forEach((style) => {
    try { style.textContent = localizeCss(style.textContent || "", input.baseUrl); }
    catch { style.remove(); input.onIssue?.("frame_stylesheet_invalid", input.baseUrl); }
  });
  rewriteRefs(doc.body, resolveInMemory, input.onIssue);

  // 事件属性与危险导航：移除 on* 事件处理器，剥离 target=_blank 等。
  doc.querySelectorAll("*").forEach((el) => {
    for (const attr of Array.from(el.attributes)) {
      if (attr.name.toLowerCase().startsWith("on")) el.removeAttribute(attr.name);
    }
    if (el.tagName.toLowerCase() === "a") {
      const href = el.getAttribute("href");
      if (href && !href.trim().startsWith("#")) el.removeAttribute("href");
      el.removeAttribute("target");
      el.removeAttribute("ping");
      el.removeAttribute("download");
    }
  });

  // 处理 frame 脚本 src：解析为本地引用，未命中则记录 issue 并丢弃。
  const frameScripts: FrameScriptSpec[] = [];
  for (const spec of scripts) {
    const ref = spec.src ? resolveInMemory(spec.src) : null;
    const asset = ref ? assetFor(ref) : null;
    if (spec.src && !asset) { input.onIssue?.("frame_script_unresolved", spec.src); continue; }
    const code = asset ? offlineAssetText(asset) : spec.code || "";
    const scan = extractScriptDependencies(code, input.baseUrl);
    const unsupported = scan.issues.some((issue) => ["unsupported_script_capability", "unsupported_script_syntax", "script_scan_limit"].includes(issue.code));
    for (const issue of scan.issues) input.onIssue?.(issue.code, issue.source);
    if (unsupported) continue;
    frameScripts.push({ code: rewriteScriptResources(code, resolveInMemory) });
  }

  doc.querySelectorAll("style").forEach((style) => { style.setAttribute("type", "text/plain"); style.setAttribute("data-offline-sheet", "true"); });
  doc.querySelectorAll("[style]").forEach((element) => {
    element.setAttribute("data-offline-style", element.getAttribute("style") || "");
    element.removeAttribute("style");
  });
  const headHtml = doc.head ? doc.head.innerHTML : "";
  const bodyHtml = doc.body ? doc.body.innerHTML : "";
  const payload = {
    assets: input.payload.assets as OfflineFrameAsset[],
    aliases: input.payload.aliases,
    baseUrl: input.baseUrl,
  };
  const runtimePayload = {
    nonce: input.nonce,
    baseUrl: input.baseUrl,
    assets: payload.assets,
    aliases: payload.aliases,
    scripts: frameScripts,
  };

  const frameHtml = [
    "<!DOCTYPE html>",
    '<html lang="en">',
    "<head>",
    '<meta charset="utf-8">',
    `<meta http-equiv="Content-Security-Policy" content="${EXPORT_FRAME_CSP}">`,
    '<meta name="viewport" content="width=device-width, initial-scale=1">',
    "<style>html,body{margin:0;padding:0;background:transparent;}body{overflow-x:hidden;}</style>",
    `<script>window.__OFFLINE_FRAME__=${escapeInlineJson(runtimePayload)};</script>`,
    `<script>${FRAME_RUNTIME_SOURCE}</script>`,
    headHtml,
    "</head>",
    "<body>",
    bodyHtml,
    "</body>",
    "</html>",
  ].join("\n");

  return { html: frameHtml, payload };
}
