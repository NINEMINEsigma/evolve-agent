/**
 * 会话导出为静态 HTML 工具模块。
 *
 * 纯函数模块，无 React 依赖。
 * 通过 DOM 克隆 + CSS 内联 + 图片 base64，
 * 将当前会话渲染状态打包为单文件 HTML。
 *
 * 设计决策：不做折叠改写，直接克隆当前 DOM 原样输出。
 * 长消息保留 CSS max-height + overflow 滚动区域。
 * 工具调用折叠状态由 CSS 控制，detail 内容在条件渲染下可能不在 DOM 中——
 * 这是 React 的限制，导出前用户可手动展开需要导出的工具调用。
 */

// ── 收集页面所有 CSS 规则 ──────────────────────────────────────

function collectStyles(): string {
  const sheets: CSSStyleSheet[] = Array.from(document.styleSheets);
  const cssTexts: string[] = [];

  for (const sheet of sheets) {
    try {
      const rules: CSSRuleList = sheet.cssRules;
      for (const rule of Array.from(rules)) {
        cssTexts.push(rule.cssText);
      }
    } catch {
      // 跨域 stylesheet 无法读取 cssRules，跳过
    }
  }

  return cssTexts.join("\n");
}

// ── 图片 base64 内联 ──────────────────────────────────────────

async function inlineImages(clone: HTMLElement): Promise<void> {
  const imgs = Array.from(clone.querySelectorAll("img"));
  const tasks = imgs.map(async (img) => {
    const src = img.getAttribute("src");
    if (!src) return;
    if (src.startsWith("data:")) return;

    try {
      const resp = await fetch(src);
      const blob = await resp.blob();
      const dataURI = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result as string);
        reader.onerror = reject;
        reader.readAsDataURL(blob);
      });
      img.setAttribute("src", dataURI);
    } catch {
      // fetch 失败，保留原始 src
    }
  });

  await Promise.all(tasks);
}

// ── 移除交互元素 ──────────────────────────────────────────────

const CLEANUP_SELECTORS = [
  ".message-actions",
  ".message-visibility-row",
  ".scroll-to-bottom",
  ".minimap-toggle",
  ".minimap",
  ".streaming-cursor",
  ".debug-badges",
];

function cleanupDOM(clone: HTMLElement): void {
  for (const selector of CLEANUP_SELECTORS) {
    clone.querySelectorAll(selector).forEach((el) => el.remove());
  }

  clone.querySelectorAll("button[onclick]").forEach((btn) => {
    btn.removeAttribute("onclick");
  });
}

// ── 入口函数 ──────────────────────────────────────────────────

/**
 * 导出当前会话为静态 HTML 文件并触发浏览器下载。
 *
 * 直接克隆 .chat-area DOM，不做折叠改写。
 * 保留当前页面的折叠/展开状态——导出前用户可自行展开需要展示的内容。
 *
 * @param sessionTitle 会话标题，用作文件名前缀和 <title>
 */
export async function exportSession(sessionTitle: string): Promise<void> {
  try {
    const chatArea = document.querySelector(".chat-area");
    if (!chatArea) {
      alert("未找到聊天区域，无法导出");
      return;
    }

    // 克隆 DOM（原样保留当前渲染状态）
    const clone = chatArea.cloneNode(true) as HTMLElement;

    // 将 SafeHtml iframe 的实际内容固化到 srcdoc 中
    // SafeHtml 通过 postMessage 注入内容，cloneNode 只克隆了空壳 srcdoc
    // iframe 的 sandbox 已添加 allow-same-origin，可直接访问 contentWindow.document
    const originalIframes = Array.from(chatArea.querySelectorAll("iframe.safe-html-iframe"));
    const clonedIframes = Array.from(clone.querySelectorAll("iframe.safe-html-iframe"));
    for (let i = 0; i < originalIframes.length && i < clonedIframes.length; i++) {
      const orig = originalIframes[i] as HTMLIFrameElement;
      const cloned = clonedIframes[i] as HTMLIFrameElement;
      try {
        const doc = orig.contentWindow?.document;
        if (doc) {
          const bodyContent = doc.body?.innerHTML || "";
          const headContent = doc.head?.outerHTML || "";
          const fullDoc = `<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>html, body { margin: 0 !important; padding: 0 !important; height: auto !important; min-height: 0 !important; background: transparent !important; } body { overflow: hidden; }</style>${headContent}</head><body>${bodyContent}</body></html>`;
          cloned.setAttribute("srcdoc", fullDoc);
          cloned.removeAttribute("sandbox");
        }
      } catch {
        // 跨域 iframe 无法读取 contentWindow，跳过
      }
    }

    // 收集 CSS
    const cssText = collectStyles();

    // CSS 变量定义（collectStyles 可能无法从构建产物中收集到 :root 规则）
    const cssVars = `:root {
  --bg-primary:   #0b0b0f;
  --bg-secondary: #131319;
  --bg-tertiary:  #1a1a22;
  --bg-hover:     #232330;
  --bg-elevated:  #1f1f29;
  --text-primary:   #e6e6ec;
  --text-secondary: #9a9aa8;
  --text-muted:     #5c5c6a;
  --accent:       #a78bfa;
  --accent-hover: #7c3aed;
  --accent-soft:  rgba(124, 58, 237, 0.14);
  --accent-glow:  rgba(167, 139, 250, 0.45);
  --accent-grad:  linear-gradient(135deg, #7c3aed 0%, #6366f1 100%);
  --multi-accent:      #22d3ee;
  --multi-accent-grad: linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%);
  --multi-accent-glow: rgba(34, 211, 238, 0.45);
  --user-bubble: #1f1f29;
  --border:        rgba(255, 255, 255, 0.06);
  --border-strong: rgba(255, 255, 255, 0.10);
  --danger: #ef4444;
  --radius:    14px;
  --radius-sm: 8px;
}`;

    // 图片 base64 内联
    await inlineImages(clone);

    // 清理交互元素
    cleanupDOM(clone);

    // 移除所有 message-content-collapsed class，取消高度限制
    clone.querySelectorAll(".message-content-collapsed").forEach((el) => {
      el.classList.remove("message-content-collapsed");
    });

    // 生成时间戳
    const now = new Date();
    const ts = now.toISOString().slice(0, 19).replace(/[T:]/g, "-");

    // 组装完整 HTML
    const html = `<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${escapeHtml(sessionTitle)}</title>
<style>
${cssVars}

${cssText}

/* 导出页面专用 */
body { background: var(--bg-primary, #0b0b0f); margin: 0; padding: 0; color: var(--text-primary, #e6e6ec); }
.chat-area { padding: 20px; max-width: 900px; margin: 0 auto; overflow: visible; height: auto; }
.message-content { max-height: none !important; overflow: visible !important; }
.tool-call-detail { max-height: none !important; overflow: visible !important; }
</style>
</head>
<body>
${clone.outerHTML}
</body>
</html>`;

    // 触发下载
    const blob = new Blob([html], { type: "text/html;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${sanitizeFilename(sessionTitle)}_${ts}.html`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch (err) {
    console.error("Export session failed:", err);
    alert("导出失败，请查看控制台获取详细信息");
  }
}

// ── 辅助函数 ──────────────────────────────────────────────────

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function sanitizeFilename(name: string): string {
  return name.replace(/[<>:"/\\|?*\x00-\x1f]/g, "_").trim() || "session";
}