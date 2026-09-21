/**
 * 会话网页抽屉 — 与"会话资源/任务"抽屉和"模型配置"抽屉并列的独立右侧抽屉。
 *
 * 通过初始探测与聊天 WebSocket Agentspace 事件实时同步 site/index.html：
 * 缺失或网络异常时显示空态并隐藏右侧触发按钮；部署成功后自动显示入口，
 * 站点资源变化时自动刷新 iframe，同时保留用户手动刷新能力。
 */

import { useEffect, useRef, useState } from "react";
import { useSessionSite } from "../hooks/useSessionSite";

interface SessionSiteDrawerProps {
  open: boolean;
  onClose: () => void;
  sessionId: string;
  onAvailabilityChange?: (available: boolean) => void;
  width?: number;
  isResizing?: boolean;
  onResizePointerDown?: (e: React.PointerEvent<HTMLElement>) => void;
}

export default function SessionSiteDrawer({
  open, onClose, sessionId, onAvailabilityChange, width, isResizing, onResizePointerDown,
}: SessionSiteDrawerProps) {
  const [isFullscreen, setIsFullscreen] = useState(false);
  const frameRef = useRef<HTMLDivElement>(null);
  const { status, reloadKey, urls, refresh } = useSessionSite(sessionId);

  // Hook 的权威探测状态决定 Layout 是否显示右侧会话网页入口。
  useEffect(() => {
    onAvailabilityChange?.(status === "ready");
  }, [status, onAvailabilityChange]);

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
    refresh();
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