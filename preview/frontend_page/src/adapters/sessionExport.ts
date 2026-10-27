import { useCallback, useEffect, useRef, useState } from "react";
import { strToU8, zipSync } from "fflate";
import type { SessionExportController, SessionExportOptions, SessionExportPhase } from "@preview-original/session-export";
import type { ExportProgress } from "@origin/features/sessionExport/types";
import labels from "../content/zh-CN.json";
import siteHtml from "../../public/demo/site/index.html?raw";
import coverSvg from "../../public/demo/cover.svg?raw";
import diagramSvg from "../../public/demo/diagram.svg?raw";
import { PREVIEW } from "../constants";
export type { SessionExportController, SessionExportOptions, SessionExportPhase } from "@preview-original/session-export";

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]!);
}

function nextStage(signal: AbortSignal): Promise<void> {
  // 阶段有独立异步边界，原弹窗可显示进度并允许取消；不请求任何后端。
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(signal.reason); return; }
    const abort = () => { window.clearTimeout(timer); signal.removeEventListener("abort", abort); reject(signal.reason); };
    const timer = window.setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, 180);
    signal.addEventListener("abort", abort, { once: true });
  });
}

export function useSessionExport(options: SessionExportOptions): SessionExportController {
  const latest = useRef(options);
  latest.current = options;
  const [isOpen, setOpen] = useState(false);
  const [phase, setPhase] = useState<SessionExportPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<ExportProgress>({ completed: 0, total: 0, bytes: 0, issues: 0 });
  const owner = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const downloads = useRef(new Map<string, number>());
  const clearDownloads = useCallback(() => {
    for (const [url, timer] of downloads.current) { window.clearTimeout(timer); URL.revokeObjectURL(url); }
    downloads.current.clear();
  }, []);
  const cancel = useCallback(() => {
    if (!owner.current) return;
    generation.current += 1;
    owner.current.abort(new DOMException("Preview export cancelled", "AbortError"));
    owner.current = null;
    setPhase("cancelled");
  }, []);
  useEffect(() => {
    setOpen(false); setPhase("idle"); setError(null);
    setProgress({ completed: 0, total: 0, bytes: 0, issues: 0 });
    const release = () => { generation.current += 1; owner.current?.abort(); owner.current = null; clearDownloads(); };
    window.addEventListener("pagehide", release);
    return () => { window.removeEventListener("pagehide", release); release(); };
  }, [options.sessionId, clearDownloads]);
  useEffect(() => {
    if ((options.processing || options.disabled) && owner.current) {
      cancel(); setError(labels.ui.exportChanged); latest.current.onNotice?.(labels.ui.exportChanged);
    }
  }, [options.processing, options.disabled, cancel]);
  const open = useCallback(() => {
    const current = latest.current;
    if (current.disabled || current.processing || !current.sessionId) return;
    if (!owner.current) { setPhase("idle"); setError(null); }
    current.onNotice?.(labels.ui.exportDemoNotice);
    setOpen(true);
  }, []);
  const close = useCallback(() => { cancel(); setOpen(false); }, [cancel]);
  const start = useCallback(async (): Promise<void> => {
    const current = latest.current;
    if (owner.current || current.disabled || current.processing || !current.sessionId) return;
    clearDownloads();
    const controller = new AbortController();
    owner.current = controller;
    const token = ++generation.current;
    const check = () => {
      controller.signal.throwIfAborted();
      if (generation.current !== token || latest.current.sessionId !== current.sessionId
        || latest.current.processing || latest.current.disabled) throw new Error(labels.ui.exportChanged);
    };
    const stage = async (value: SessionExportPhase, completed: number, bytes: number) => {
      check(); setPhase(value); setProgress({ completed, total: 5, bytes, issues: 0 });
      await nextStage(controller.signal); check();
    };
    setError(null);
    latest.current.onNotice?.(labels.ui.exportDemoNotice);
    try {
      await stage("capturing", 0, 0);
      const description = labels.ui.exportReadme;
      const page = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'none'; connect-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; frame-src 'none'; base-uri 'none'; form-action 'none'"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHtml(labels.ui.exportTitle)}</title><style>body{max-width:900px;margin:48px auto;padding:0 24px;background:#101923;color:#dce8f3;font:16px/1.8 system-ui,sans-serif}h1{font-size:30px}aside{border-left:3px solid #91d9bd;padding:12px 20px;background:#192c34}img{width:100%;height:auto;border-radius:12px}pre{white-space:pre-wrap;font:inherit}a{color:#91d9bd}</style></head><body><h1>${escapeHtml(labels.ui.exportFileTitle)}</h1><aside>${escapeHtml(description)}</aside><p>${escapeHtml(current.sessionId)}</p><img src="cover.svg" alt="${escapeHtml(labels.sessions.coverAlt)}"><pre>${escapeHtml(labels.sessions.final)}</pre><img src="diagram.svg" alt="${escapeHtml(labels.ui.exportFileTitle)}"><p><a href="site/index.html">${escapeHtml(labels.ui.exportTitle)}</a></p></body></html>`;
      const files = {
        "index.html": strToU8(page), "README.txt": strToU8(description),
        "cover.svg": strToU8(coverSvg), "diagram.svg": strToU8(diagramSvg),
        "site/index.html": strToU8(siteHtml),
        "manifest.json": strToU8(JSON.stringify({ kind: "preview-demonstration", version: PREVIEW.version,
          session_id: current.sessionId, generated_at: PREVIEW.timestamp, real_session_backup: false,
          full_offline_export: false, description, stage_paused: current.stagePaused, chat_style_paused: current.chatStylePaused }, null, 2)),
      };
      const bytes = Object.values(files).reduce((sum, value) => sum + value.byteLength, 0);
      await stage("collecting", 2, bytes);
      await stage("packing", 3, bytes);
      const archive = new Blob([new Uint8Array(zipSync(files))], { type: "application/zip" });
      await stage("verifying", 4, bytes);
      check();
      const url = URL.createObjectURL(archive);
      const link = document.createElement("a");
      link.href = url;
      link.download = `evolve-preview-demo-${current.sessionId.replace(/[^a-zA-Z0-9_-]/g, "_")}.zip`;
      document.body.append(link);
      try { check(); link.click(); }
      catch (cause) { URL.revokeObjectURL(url); throw cause; }
      finally { link.remove(); }
      const timer = window.setTimeout(() => { URL.revokeObjectURL(url); downloads.current.delete(url); }, 60000);
      downloads.current.set(url, timer);
      setProgress({ completed: 5, total: 5, bytes: archive.size, issues: 0 });
      setPhase("succeeded");
    } catch (cause) {
      if (token !== generation.current) return;
      const message = cause instanceof Error ? cause.message : labels.ui.exportFailed;
      setError(message); setPhase("failed"); latest.current.onNotice?.(message);
    } finally {
      controller.abort();
      if (owner.current === controller) owner.current = null;
    }
  }, [clearDownloads]);
  return { isOpen, phase, error, progress, open, close, start, cancel, busy: ["capturing", "collecting", "packing", "verifying"].includes(phase) };
}
