/**
 * 在 assistant 消息气泡中通过 iframe 渲染 AI 输出的原始 HTML。
 *
 * 使用 iframe + srcDoc 把 agent 内容隔离在独立文档中，CSS 和 JS 不会污染外层页面；
 * 同时通过 postMessage 把内容高度同步给父组件，让 iframe 高度自适应内容，
 * 避免内部出现滚动条或过大空白。
 */

import React, { useEffect, useId, useMemo, useState } from "react";

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

function buildHeightSyncScript(instanceId: string): string {
  return `
<script>
(function () {
  const id = ${JSON.stringify(instanceId)};
  let lastHeight = 0;

  function sendHeight() {
    const body = document.body;
    const html = document.documentElement;
    if (!body || !html) return;

    // 优先使用 body 实际内容高度，避免 html.scrollHeight 包含额外空白
    const bodyHeight = Math.max(
      body.getBoundingClientRect().height,
      body.scrollHeight,
      body.offsetHeight
    );
    const height = bodyHeight > 0 ? bodyHeight : html.scrollHeight;

    if (height === lastHeight) return;
    lastHeight = height;
    if (window.parent && window.parent !== window) {
      window.parent.postMessage(
        { type: "safe-html-resize", id, height },
        "*"
      );
    }
  }

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

function buildHtmlDocument(rawHtml: string, instanceId: string): string {
  const script = buildHeightSyncScript(instanceId);

  if (/<html\b/i.test(rawHtml) && /<\/body>/i.test(rawHtml)) {
    return rawHtml.replace(/<\/body>/i, `${script}\n</body>`);
  }

  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>${BASE_RESET_STYLE}</style>
</head>
<body>${rawHtml}${script}</body>
</html>`;
}

export default function SafeHtml({ html, className }: SafeHtmlProps) {
  const [height, setHeight] = useState(0);
  const id = useId();

  const srcDoc = useMemo(() => buildHtmlDocument(html, id), [html, id]);

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
      className={`safe-html-iframe ${className || ""}`.trim()}
      srcDoc={srcDoc}
      style={iframeStyle}
      sandbox="allow-scripts allow-popups allow-forms"
      title="agent-rendered-content"
    />
  );
}