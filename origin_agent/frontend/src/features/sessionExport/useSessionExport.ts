import { useCallback, useEffect, useRef, useState } from "react";
import { captureSessionExport, readSessionExportResource, verifySessionExport, SessionExportRequestError } from "./api";
import { collectExportResources } from "./resourceGraph";
import { buildSessionExportArchive, makeOfflineData } from "./archive";
import { EXPORT_LIMITS } from "./limits";
import { exportLabels } from "./labels";
import type { ExportProgress } from "./types";

export type SessionExportPhase = "idle" | "capturing" | "collecting" | "packing" | "verifying" | "succeeded" | "failed" | "cancelled";
export interface SessionExportOptions {
  sessionId: string;
  processing: boolean;
  disabled: boolean;
  stagePaused: boolean;
  chatStylePaused: boolean;
  onNotice?: (message: string) => void;
}
export function useSessionExport(options: SessionExportOptions) {
  const latest = useRef(options);
  latest.current = options;
  const [isOpen, setOpen] = useState(false);
  const [phase, setPhase] = useState<SessionExportPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<ExportProgress>({ completed: 0, total: 0, bytes: 0, issues: 0 });
  const active = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const downloads = useRef<Array<{ url: string; timer: number }>>([]);
  const clearDownloads = useCallback(() => {
    for (const entry of downloads.current) { window.clearTimeout(entry.timer); URL.revokeObjectURL(entry.url); }
    downloads.current = [];
  }, []);
  const cancel = useCallback(() => {
    if (!active.current) return;
    generation.current += 1;
    active.current.abort(new DOMException("Export cancelled", "AbortError"));
    active.current = null;
    setPhase("cancelled");
  }, []);
  useEffect(() => {
    setOpen(false);
    setPhase("idle"); setError(null);
    return () => { generation.current += 1; active.current?.abort(); active.current = null; clearDownloads(); };
  }, [options.sessionId, clearDownloads]);
  useEffect(() => {
    if ((options.processing || options.disabled) && active.current) {
      cancel(); setError(exportLabels.changed); latest.current.onNotice?.(exportLabels.changed);
    }
  }, [options.processing, options.disabled, cancel]);
  const open = useCallback(() => {
    if (latest.current.disabled || latest.current.processing || !latest.current.sessionId) return;
    if (!active.current) { setPhase("idle"); setError(null); }
    setOpen(true);
  }, []);
  const close = useCallback(() => { cancel(); setOpen(false); }, [cancel]);
  const start = useCallback(async () => {
    if (active.current || latest.current.disabled || latest.current.processing || !latest.current.sessionId) return;
    clearDownloads();
    const owner = latest.current;
    const sid = owner.sessionId;
    const token = ++generation.current;
    const controller = new AbortController();
    active.current = controller;
    const totalDeadline = performance.now() + EXPORT_LIMITS.totalMs;
    const check = () => {
      if (controller.signal.aborted) throw controller.signal.reason;
      if (performance.now() > totalDeadline) throw new Error("Export exceeded total time budget");
      if (generation.current !== token || latest.current.sessionId !== sid || latest.current.processing || latest.current.disabled) throw new Error(exportLabels.changed);
    };
    const timeout = window.setTimeout(() => controller.abort(new Error("Export exceeded total time budget")), EXPORT_LIMITS.totalMs);
    setPhase("capturing"); setError(null); setProgress({ completed: 0, total: 0, bytes: 0, issues: 0 });
    try {
      const snapshot = await captureSessionExport(sid, controller.signal);
      check(); setPhase("collecting");
      const collection = await collectExportResources(snapshot, {
        read: (source, signal) => readSessionExportResource(sid, snapshot.stamp, source, signal),
      }, {
        signal: controller.signal, baseUrl: window.location.href,
        onProgress: (value) => { if (token === generation.current) setProgress(value); },
      });
      check(); setPhase("packing");
      const data = makeOfflineData(snapshot, collection, { stagePaused: owner.stagePaused, chatStylePaused: owner.chatStylePaused });
      check();
      const archive = await buildSessionExportArchive({ data, signal: controller.signal }, controller.signal);
      check(); setPhase("verifying");
      await verifySessionExport(sid, { stamp: snapshot.stamp, resources: collection.proofs }, controller.signal);
      check();
      const url = URL.createObjectURL(archive);
      const link = document.createElement("a");
      const title = (snapshot.title || "session").replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_").slice(0, 80).trim() || "session";
      link.href = url;
      link.download = `${title}_${sid}_${new Date().toISOString().replace(/[:.]/g, "-")}.zip`;
      document.body.appendChild(link);
      try { link.click(); }
      catch (cause) { URL.revokeObjectURL(url); throw cause; }
      finally { link.remove(); }
      const entry = { url, timer: 0 };
      entry.timer = window.setTimeout(() => {
        URL.revokeObjectURL(url); downloads.current = downloads.current.filter((item) => item !== entry);
      }, EXPORT_LIMITS.downloadRevokeMs);
      downloads.current.push(entry);
      setPhase("succeeded");
    } catch (cause) {
      if (token !== generation.current) return;
      const message = cause instanceof SessionExportRequestError
        ? `[${cause.code} HTTP ${cause.status}] ${cause.message}`
        : cause instanceof Error ? cause.message : "Export failed";
      setError(message); setPhase("failed"); latest.current.onNotice?.(`${exportLabels.failed} ${message}`);
    } finally {
      window.clearTimeout(timeout);
      controller.abort();
      if (active.current === controller) active.current = null;
    }
  }, [clearDownloads]);
  return { isOpen, phase, error, progress, open, start, cancel, close, busy: ["capturing", "collecting", "packing", "verifying"].includes(phase) };
}
export type SessionExportController = ReturnType<typeof useSessionExport>;
