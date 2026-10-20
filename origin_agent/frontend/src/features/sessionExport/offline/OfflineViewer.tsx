/**
 * 离线会话阅读器主视图。
 *
 * 完全离线：不连接 Gateway、不 fetch 原服务。严格校验惰性 JSON 数据后，
 * 主资源运行期把 base64 资源解码为本地 Blob URL；按 50 行一批 rAF 追加挂载
 * 全部历史普通行（无虚拟列表/分页），工具详情按本地选择渲染且原始内容始终保留。
 * 默认全保留 system 消息，不调用在线显示偏好过滤。
 *
 * stage 重新在隔离 frame 中运行；chat style 经共享作用域处理并按本地资源重写后注入。
 * 缺失/不支持资源汇总到顶部清单。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChatMessage } from "../../../types";
import type { ExportIssue, OfflineExportData } from "../types";
import { historyContentRowToChatMessage } from "../../chat/historyProjection";
import { parseToolResult } from "../../../utils";
import { MessageRenderProvider, type MessageRenderEnvironment, type MessageResourceKind } from "../../../components/primitives/MessageRenderEnvironment";
import { EXPORT_LIMITS } from "../limits";
import { scopeSessionChatCss } from "../../../utils/chatStyleProcessing";
import { createOfflineAssetUrls, offlineAssetText, type OfflineResourceRuntime } from "./resourceRuntime";
import { rewriteCssRefs } from "./sandboxRuntime";
import OfflineMessage from "./OfflineMessage";
import Lightbox from "../../../components/Lightbox";
import OfflineHtmlFrame from "./OfflineHtmlFrame";
import { exportLabels } from "../labels";

const VISUAL_KIND_STAGE = "stage" as const;
const VISUAL_KIND_CHAT_STYLE = "chat_style" as const;

/** 净化 Mermaid 生成的 SVG：删除脚本、外部/动态链接与内联事件属性。 */
function sanitizeMermaidSvg(svg: string): string {
  const template = document.createElement("template");
  template.innerHTML = svg;
  template.content.querySelectorAll("script,iframe,object,embed,link,meta,base").forEach((node) => node.remove());
  for (const element of template.content.querySelectorAll("*")) {
    for (const attribute of Array.from(element.attributes)) {
      const name = attribute.name.toLowerCase();
      if (name.startsWith("on") || ["src", "srcset", "poster"].includes(name)
        || (["href", "xlink:href"].includes(name) && !attribute.value.startsWith("#"))) element.removeAttribute(attribute.name);
    }
    if (element.hasAttribute("style")) {
      try { element.setAttribute("style", rewriteCssRefs(element.getAttribute("style") || "", () => null)); }
      catch { element.removeAttribute("style"); }
    }
    if (element.tagName.toLowerCase() === "style") {
      try { element.textContent = rewriteCssRefs(element.textContent || "", () => null); }
      catch { element.remove(); }
    }
  }
  return template.innerHTML;
}

/** 把离线数据校验并转成稳定视图；未知字段快速失败。 */
function collectMessages(data: OfflineExportData): ChatMessage[] {
  return data.snapshot.rows.map((row) => {
    const message = historyContentRowToChatMessage(row);
    const result = message.toolCard?.result;
    if (result && typeof result.content === "string") {
      const extras = parseToolResult(result.content, message.toolName);
      return { ...message, toolCard: { ...message.toolCard!, result: { ...result, imageMarkdown: extras.imageMarkdown, downloadInfo: extras.downloadInfo } } };
    }
    if (message.role === "tool" && typeof message.content === "string") {
      const extras = parseToolResult(message.content, message.toolName);
      return { ...message, imageMarkdown: extras.imageMarkdown, downloadInfo: extras.downloadInfo };
    }
    return message;
  });
}

function IssueList({ issues }: { issues: ExportIssue[] }) {
  const [open, setOpen] = useState(false);
  if (issues.length === 0) return null;
  return (
    <section className="offline-issues">
      <button type="button" className="offline-issues-toggle" onClick={() => setOpen((value) => !value)}>
        {exportLabels.issues} ({issues.length})
      </button>
      {open && (
        <ul className="offline-issues-list">
          {issues.map((issue, index) => (
            <li key={`${issue.code}-${index}`} className="offline-issue">
              <span className="offline-issue-code">{issue.code}</span>
              <span className="offline-issue-owner">{issue.owner}</span>
              {issue.source && <span className="offline-issue-source">{issue.source}</span>}
              {issue.detail ? <span className="offline-issue-detail">{issue.detail}</span> : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default function OfflineViewer({ data }: { data: OfflineExportData }) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [issues, setIssues] = useState<ExportIssue[]>(() => data.issues.slice());
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [image, setImage] = useState<string | null>(null);
  const [stageEnabled, setStageEnabled] = useState(!data.stagePaused);
  const [chatStyleEnabled, setChatStyleEnabled] = useState(!data.chatStylePaused);

  const runtime = useMemo<OfflineResourceRuntime>(() => createOfflineAssetUrls(data), [data]);

  const reportIssue = useCallback((owner: string, code: string, detail: string) => {
    setIssues((current) => {
      if (current.some((issue) => issue.code === code && issue.detail === detail && issue.owner === owner)) {
        return current;
      }
      if (current.length >= EXPORT_LIMITS.resources * 2) return current;
      return [...current, { owner, source: owner, code, detail: detail.slice(0, 500) }];
    });
  }, []);

  const environment = useMemo<MessageRenderEnvironment>(() => ({
    mode: "offline",
    resolveResource(raw: string, _kind: MessageResourceKind) {
      return runtime.resolve(raw, _kind);
    },
    renderHtml(html: string) {
      return (
        <OfflineHtmlFrame
          html={html}
          runtime={runtime}
          baseUrl={data.originalBaseUrl}
          onIssue={(code, detail) => reportIssue("html", code, detail)}
        />
      );
    },
    renderIframe() {
      return <div className="offline-frame-placeholder">{exportLabels.unavailable}</div>;
    },
    onCopyFailure: () => reportIssue("copy", "clipboard_unavailable", exportLabels.copyFailed),
    sanitizeSvg: sanitizeMermaidSvg,
    reportIssue: (code: string, detail: string) => reportIssue("render", code, detail),
    labels: {
      diagramFailed: exportLabels.diagramFailed,
      frameOpen: exportLabels.frameOpen,
      attachment: exportLabels.attachment,
      copyFailed: exportLabels.copyFailed,
      resourceUnavailable: exportLabels.unavailable,
    },
  }), [data.originalBaseUrl, reportIssue, runtime]);

  // 50 行一批 rAF 追加，最终挂载全部历史普通行。
  useEffect(() => {
    const all = collectMessages(data);
    let cancelled = false;
    let cursor = 0;
    let frame = 0;
    setMessages([]);
    const step = () => {
      if (cancelled) return;
      const next = all.slice(cursor, cursor + EXPORT_LIMITS.renderBatch);
      cursor += next.length;
      if (next.length > 0) setMessages((current) => current.concat(next));
      if (cursor < all.length) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => {
      cancelled = true;
      cancelAnimationFrame(frame);
    };
  }, [data]);

  useEffect(() => () => runtime.dispose(), [runtime]);

  // chat style：共享作用域处理 + 本地资源重写后注入。
  const chatStyleUrl = data.visualEntries[VISUAL_KIND_CHAT_STYLE];
  useEffect(() => {
    if (!chatStyleEnabled || !chatStyleUrl) return;
    let cancelled = false;
    let styleEl: HTMLStyleElement | null = null;
    const run = async () => {
      const source = decodeOfflineAssetText(runtime, chatStyleUrl);
      if (source == null) {
        reportIssue("chat_style", "chat_style_missing", chatStyleUrl);
        return;
      }
      const scoped = await scopeSessionChatCss(source, chatStyleUrl, (raw, base) => {
        if (raw.startsWith("#")) return raw;
        const local = runtime.resolve(new URL(raw, base).href, "image");
        if (!local) reportIssue("chat_style", "chat_style_resource_unresolved", raw);
        return local || "data:,";
      });
      if (cancelled) return;
      if (!scoped.ok) {
        reportIssue("chat_style", "chat_style_scope_failed", scoped.error);
        return;
      }
      styleEl = document.createElement("style");
      styleEl.setAttribute("data-chat-style-scope", "");
      styleEl.textContent = scoped.css;
      document.head.appendChild(styleEl);
    };
    void run().catch((error) => {
      if (!cancelled) reportIssue("chat_style", "chat_style_load_failed", error instanceof Error ? error.message : String(error));
    });
    return () => {
      cancelled = true;
      styleEl?.remove();
    };
  }, [chatStyleEnabled, chatStyleUrl, data, reportIssue, runtime]);

  const stageHtmlRaw = data.visualEntries[VISUAL_KIND_STAGE];
  const stageHtml = useMemo(
    () => (stageHtmlRaw ? decodeOfflineAssetText(runtime, stageHtmlRaw) : null),
    [runtime, stageHtmlRaw],
  );

  useEffect(() => {
    if (stageHtmlRaw && stageHtml === null) reportIssue("stage", "invalid_visual_text", stageHtmlRaw);
  }, [stageHtmlRaw, stageHtml, reportIssue]);

  return (
    <MessageRenderProvider environment={environment}>
      <div className="offline-root" ref={rootRef}>
        <div className="offline-stage-background">
          {stageEnabled && stageHtml ? (
            <OfflineHtmlFrame
              html={stageHtml}
              runtime={runtime}
              baseUrl={stageHtmlRaw || data.originalBaseUrl}
              onIssue={(code, detail) => reportIssue("stage", code, detail)}
              defaultExpanded
              className="offline-stage-frame"
            />
          ) : null}
        </div>
        <header className="offline-header">
          <div className="offline-title">{data.snapshot.title || data.snapshot.session_id}</div>
          <div className="offline-meta">
            <span className="offline-session-id">{data.snapshot.session_id}</span>
            <span className="offline-captured-at">{data.snapshot.captured_at}</span>
            {data.snapshot.tags.map((tag) => (
              <span className="offline-tag" key={tag}>{tag}</span>
            ))}
          </div>
          <div className="offline-controls">
            <label className="offline-toggle">
              <input type="checkbox" checked={stageEnabled} onChange={(e) => setStageEnabled(e.target.checked)} />
              {exportLabels.stage}
            </label>
            <label className="offline-toggle">
              <input type="checkbox" checked={chatStyleEnabled} onChange={(e) => setChatStyleEnabled(e.target.checked)} />
              {exportLabels.chatStyle}
            </label>
          </div>
          <p>{exportLabels.limitations}</p>
          {stageHtml && <details><summary>{exportLabels.stage} · {exportLabels.source}</summary><pre>{stageHtml}</pre></details>}
          <IssueList issues={issues} />
        </header>
        <main className="chat-area offline-chat-area">
          <div className="chat-content offline-chat-content">
            {messages.map((message) => (
              <div className="chat-history-row chat-history-row--history" key={message.id}>
                <OfflineMessage message={message} onImageClick={setImage} />
              </div>
            ))}
          </div>
        </main>
        {image && <Lightbox src={image} onClose={() => setImage(null)} />}
      </div>
    </MessageRenderProvider>
  );
}

/** 从离线资产表读取单个文本资源（chat style CSS / stage HTML / viewer 资源）。 */
function decodeOfflineAssetText(runtime: OfflineResourceRuntime, ref: string): string | null {
  const trimmed = ref.trim();
  if (!trimmed) return null;
  if (trimmed.startsWith("data:")) {
    const comma = trimmed.indexOf(",");
    if (comma < 0) return null;
    const meta = trimmed.slice(5, comma);
    const payload = trimmed.slice(comma + 1);
    try {
      return /;base64/i.test(meta) ? atob(payload) : decodeURIComponent(payload);
    } catch {
      return null;
    }
  }
  const assetRef = runtime.assetRefFor(trimmed);
  if (!assetRef) return null;
  const id = assetRef.slice("export-asset:".length);
  const asset = runtime.assetOf(id);
  if (!asset) return null;
  try {
    return offlineAssetText(asset);
  } catch {
    return null;
  }
}