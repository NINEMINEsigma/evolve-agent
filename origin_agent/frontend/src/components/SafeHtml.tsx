/**
 * 在 assistant 消息气泡中通过 iframe 渲染 AI 输出的原始 HTML。
 *
 * 使用 iframe 把 agent 内容隔离在独立文档中，CSS 和 JS 不会污染外层页面；
 * 通过 postMessage 向 iframe 内部发送完整 HTML，由 iframe 内部脚本只更新 body 内容，
 * 避免 srcDoc 每次变化都导致整页重新加载，从而消除流式输出时的闪烁。
 * 同时通过 postMessage 把内容高度同步给父组件，让 iframe 高度自适应内容。
 */

import React, { useEffect, useId, useRef, useState } from "react";

interface SafeHtmlProps {
  html: string;
  className?: string;
}

const BASE_RESET_STYLE = `
  html, body {
    margin: 0 !important;
    padding: 0 !important;
    height: auto !important;
    min-height: 0 !important;
    background: transparent !important;
  }
  body { overflow: hidden; }
`;

const DYNAMIC_MARKER = "data-safe-html-dynamic";

function buildShellScript(instanceId: string): string {
  return `
<script>
(function () {
  const id = ${JSON.stringify(instanceId)};
  const DYNAMIC_MARKER = ${JSON.stringify(DYNAMIC_MARKER)};
  let lastHeight = 0;

  function sendHeight() {
    const body = document.body;
    const html = document.documentElement;
    if (!body || !html) return;

    const bodyHeight = Math.max(
      body.getBoundingClientRect().height,
      body.scrollHeight,
      body.offsetHeight
    );
    const height = bodyHeight > 0 ? bodyHeight : html.scrollHeight;

    if (height === lastHeight) return;
    lastHeight = height;
    if (window.parent && window.parent !== window) {
      window.parent.postMessage({ type: "safe-html-resize", id, height }, "*");
    }
  }

  function reexecuteScripts(root) {
    root.querySelectorAll("script").forEach((oldScript) => {
      const newScript = document.createElement("script");
      for (let i = 0; i < oldScript.attributes.length; i++) {
        const attr = oldScript.attributes[i];
        newScript.setAttribute(attr.name, attr.value);
      }
      newScript.textContent = oldScript.textContent;
      oldScript.replaceWith(newScript);
    });
  }

  function clearDynamicHead() {
    document.head.querySelectorAll("[" + DYNAMIC_MARKER + "]").forEach((el) => el.remove());
  }

  function setHeadFromHtml(headHtml) {
    if (!headHtml) return;
    const temp = document.createElement("div");
    temp.innerHTML = headHtml;
    temp.querySelectorAll("style, link, script, meta, title, base").forEach((tag) => {
      tag.setAttribute(DYNAMIC_MARKER, "true");
      document.head.appendChild(tag);
    });
    reexecuteScripts(document.head);
  }

  function updateHtml(rawHtml) {
    try {
      let bodyHtml = rawHtml || "";
      let headHtml = "";

      if (/<html\\b/i.test(rawHtml)) {
        const bodyMatch = rawHtml.match(/<body[^>]*>([\\s\\S]*)<\\/body>/i);
        if (bodyMatch) bodyHtml = bodyMatch[1];
        const headMatch = rawHtml.match(/<head[^>]*>([\\s\\S]*)<\\/head>/i);
        if (headMatch) headHtml = headMatch[1];
      }

      clearDynamicHead();
      if (headHtml) setHeadFromHtml(headHtml);
      document.body.innerHTML = bodyHtml;
      reexecuteScripts(document.body);
      sendHeight();
    } catch (err) {
      console.error("[SafeHtml] updateHtml failed:", err);
    }
  }

  window.addEventListener("message", (event) => {
    if (!event.data || event.data.type !== "safe-html-update") return;
    if (event.data.id !== id) return;
    updateHtml(event.data.html);
  });

  sendHeight();

  if (document.readyState === "complete") {
    sendHeight();
  } else {
    window.addEventListener("load", sendHeight);
  }

  window.addEventListener("resize", sendHeight);

  if (typeof ResizeObserver !== "undefined") {
    const ro = new ResizeObserver(sendHeight);
    ro.observe(document.body);
  }

  if (typeof MutationObserver !== "undefined") {
    const mo = new MutationObserver(sendHeight);
    mo.observe(document.body, { childList: true, subtree: true, attributes: true });
  }
})();
</script>
  `.trim();
}

function buildShellDocument(instanceId: string): string {
  const script = buildShellScript(instanceId);
  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>${BASE_RESET_STYLE}</style>
</head>
<body>${script}</body>
</html>`;
}

export default function SafeHtml({ html, className }: SafeHtmlProps) {
  const [height, setHeight] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const id = useId();
  const iframeRef = useRef<HTMLIFrameElement>(null);

  const sendHtml = (targetHtml: string) => {
    const contentWindow = iframeRef.current?.contentWindow;
    if (!contentWindow) return;
    contentWindow.postMessage({ type: "safe-html-update", id, html: targetHtml }, "*");
  };

  useEffect(() => {
    if (loaded) {
      sendHtml(html);
    }
  }, [html, loaded, id]);

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (event.data?.type !== "safe-html-resize") return;
      if (event.data.id !== id) return;
      setHeight(event.data.height);
    };
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [id]);

  const iframeStyle: React.CSSProperties = {
    width: "100%",
    height: height > 0 ? `${height}px` : "60px",
    border: "none",
    display: "block",
    background: "transparent",
  };

  return (
    <iframe
      ref={iframeRef}
      className={`safe-html-iframe ${className || ""}`.trim()}
      srcDoc={buildShellDocument(id)}
      onLoad={() => setLoaded(true)}
      style={iframeStyle}
      sandbox="allow-scripts allow-popups allow-forms"
      title="agent-rendered-content"
    />
  );
}