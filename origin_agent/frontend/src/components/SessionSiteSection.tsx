/**
 * 会话网页抽屉 — 与"会话资源/任务"抽屉和"模型配置"抽屉并列的独立右侧抽屉。
 *
 * 拉模式探测：打开或 sessionId 变化时 fetch 一次 index.html，
 * 404/网络异常 → 空态"尚未部署网页"；
 * 200 → toolbar 一行 + iframe 撑满剩余空间（自适应宽高、无冗余边框）。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { buildSiteUrls } from "../utils";

interface SessionSiteDrawerProps {
  open: boolean;
  onClose: () => void;
  sessionId: string;
  width?: number;
  isResizing?: boolean;
  onResizePointerDown?: (e: React.PointerEvent<HTMLElement>) => void;
}

type ProbeStatus = "idle" | "missing" | "ready";

export default function SessionSiteDrawer({
  open, onClose, sessionId, width, isResizing, onResizePointerDown,
}: SessionSiteDrawerProps) {
  const [status, setStatus] = useState<ProbeStatus>("idle");
  const [reloadKey, setReloadKey] = useState(0);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const frameRef = useRef<HTMLDivElement>(null);
  const probeSeqRef = useRef(0);

  const urls = buildSiteUrls(sessionId);

  const probe = useCallback(async () => {
    if (!urls) {
      setStatus("missing");
      return;
    }
    const seq = ++probeSeqRef.current;
    try {
      const resp = await fetch(urls.indexUrl, { cache: "no-store" });
      if (seq !== probeSeqRef.current) return;
      setStatus(resp.ok ? "ready" : "missing");
    } catch {
      if (seq !== probeSeqRef.current) return;
      setStatus("missing");
    }
  }, [urls]);

  // sessionId 变化：重置状态并重新探测
  useEffect(() => {
    setStatus("idle");
    setReloadKey(0);
    if (open) {
      probe();
    }
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  // open 由 false→true 时探测
  useEffect(() => {
    if (open && status === "idle") {
      probe();
    }
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  // 全屏状态同步
  useEffect(() => {
    const onFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", onFullscreenChange);
  }, []);

  if (!open) return null;

  const handleRefresh = () => {
    probe();
    setReloadKey((k) => k + 1);
  };

  const handleFullscreen = () => {
    if (document.fullscreenElement) {
      document.exitFullscreen();
    } else {
      frameRef.current?.requestFullscreen();
    }
  };

  const handleNewTab = () => {
    if (urls) window.open(urls.indexUrl, "_blank");
  };

  const handleDownloadZip = () => {
    if (urls) window.open(urls.zipUrl, "_blank");
  };

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer-panel site-drawer-panel" style={width != null ? { width } : undefined} onClick={(e) => e.stopPropagation()}>
        <div className="drawer-header">
          <span className="drawer-title">会话网页</span>
          <button className="drawer-close" onClick={onClose}>✕</button>
        </div>
        <div className="drawer-body site-drawer-body">
          {status === "missing" || status === "idle" ? (
            <div className="drawer-empty">尚未部署网页</div>
          ) : (
            <>
              <div className="site-toolbar">
                <button className="site-btn" onClick={handleRefresh} title="刷新">刷新</button>
                <button className="site-btn" onClick={handleFullscreen} title="全屏">
                  {isFullscreen ? "退出全屏" : "全屏"}
                </button>
                <button className="site-btn" onClick={handleNewTab} title="新标签页打开">新标签页</button>
                <button className="site-btn" onClick={handleDownloadZip} title="下载整站 zip">下载</button>
              </div>
              <div className="site-viewport" ref={frameRef}>
                <iframe
                  key={reloadKey}
                  src={urls?.indexUrl}
                  sandbox="allow-scripts allow-popups allow-forms allow-same-origin"
                  allowFullScreen
                  title="session-site"
                />
              </div>
            </>
          )}
        </div>
        {onResizePointerDown && (
          <div
            className={`drawer-resize-handle ${isResizing ? "dragging" : ""}`}
            onPointerDown={onResizePointerDown}
            data-tooltip="拖拽调整抽屉宽度"
          />
        )}
      </div>
    </div>
  );
}