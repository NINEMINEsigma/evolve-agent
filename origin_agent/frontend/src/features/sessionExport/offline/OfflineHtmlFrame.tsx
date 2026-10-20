import { useEffect, useMemo, useRef, useState } from "react";
import { buildOfflineFrame } from "./sandboxRuntime";
import type { OfflineResourceRuntime } from "./resourceRuntime";
import { extractDocumentDependencies } from "../documentDependencies";
import { exportLabels } from "../labels";

interface OfflineHtmlFrameProps {
  html: string;
  runtime: OfflineResourceRuntime;
  baseUrl: string;
  onIssue: (code: string, detail: string) => void;
  defaultExpanded?: boolean;
  className?: string;
}
let frameNonceCounter = 0;
const FRAME_ISSUE_CODES = new Set([
  "offline_fetch_unmatched", "offline_comm_disabled", "unsupported_script_capability",
  "offline_runtime_error", "offline_unhandled_rejection", "offline_csp_violation",
  "offline_script_missing", "offline_script_error", "offline_asset_missing", "offline_json_unavailable",
]);
export default function OfflineHtmlFrame({ html, runtime, baseUrl, onIssue, defaultExpanded = false, className }: OfflineHtmlFrameProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [height, setHeight] = useState(120);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const onIssueRef = useRef(onIssue);
  onIssueRef.current = onIssue;
  const nonce = useMemo(() => `frame-${Date.now()}-${frameNonceCounter++}`, []);
  useEffect(() => {
    if (!expanded) { setBlobUrl(null); return; }
    let url: string | null = null;
    try {
      const scan = extractDocumentDependencies(html, baseUrl, "html");
      for (const issue of scan.issues) onIssueRef.current(issue.code, issue.source);
      const refs = scan.dependencies.flatMap((item) => {
        try { return [new URL(item.url, item.baseUrl).href]; }
        catch { onIssueRef.current("invalid_resource_url", item.url); return []; }
      });
      const payload = runtime.collectFrameAssets(refs, baseUrl);
      const frame = buildOfflineFrame({ html, payload, nonce, baseUrl, onIssue: (code, detail) => onIssueRef.current(code, detail) });
      url = URL.createObjectURL(new Blob([frame.html], { type: "text/html" }));
      setBlobUrl(url);
    } catch (error) {
      setBlobUrl(null);
      onIssueRef.current("frame_build_failed", error instanceof Error ? error.message : "Frame could not be prepared");
    }
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [html, baseUrl, runtime, expanded, nonce]);
  useEffect(() => {
    let reports = 0;
    const handler = (event: MessageEvent) => {
      if (!iframeRef.current || event.source !== iframeRef.current.contentWindow) return;
      const data: unknown = event.data;
      if (!data || typeof data !== "object" || Array.isArray(data)) return;
      const message = data as Record<string, unknown>;
      if (message.nonce !== nonce) return;
      if (message.type === "offline-frame-issue" && typeof message.code === "string"
        && FRAME_ISSUE_CODES.has(message.code) && typeof message.detail === "string" && message.detail.length <= 500 && reports++ < 128) {
        onIssueRef.current(message.code, message.detail);
      }
      if (message.type === "offline-frame-resize" && typeof message.height === "number" && Number.isFinite(message.height)) setHeight(Math.max(60, Math.min(8000, Math.round(message.height))));
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [nonce]);
  const stage = className?.includes("offline-stage-frame");
  return (
    <div className={`offline-html-frame${className ? ` ${className}` : ""}`}>
      {!stage && <button type="button" onClick={() => setExpanded((value) => !value)}>{expanded ? exportLabels.collapse : exportLabels.frameOpen}</button>}
      {expanded && blobUrl && <iframe ref={iframeRef} src={blobUrl} sandbox="allow-scripts" referrerPolicy="no-referrer" title="offline-html" style={{ width: "100%", height: stage ? "100%" : `${height}px`, border: 0, display: "block" }} />}
      {!stage && <details><summary>{exportLabels.source}</summary><pre>{html}</pre></details>}
    </div>
  );
}
