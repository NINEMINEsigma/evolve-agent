import { useEffect, useRef, useState } from "react";
import type { TabRenderContext } from "./registry";

/**
 * Session site tab: iframe preview + bottom toolbar for ws:sessions/<id>/site/.
 * Probe state is injected via ctx.siteStatus (single probe source lives in
 * useTabSystem); this component only renders and refreshes.
 */
export default function SiteTab({ ctx }: { ctx: TabRenderContext }) {
  const [isFullscreen, setIsFullscreen] = useState(false);
  const frameRef = useRef<HTMLDivElement>(null);
  const { status, reloadKey, urls, refresh } = ctx.siteStatus;

  // Fullscreen state sync
  useEffect(() => {
    const onFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", onFullscreenChange);
  }, []);

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
    <div className="site-tab">
      <div className="site-tab-body">
        {status === "missing" || status === "idle" ? (
          <div className="drawer-empty">尚未部署网页</div>
        ) : (
          <>
            <div className="site-viewport" ref={frameRef}>
              <iframe
                key={reloadKey}
                src={urls?.indexUrl}
                sandbox="allow-scripts allow-popups allow-forms allow-same-origin"
                allowFullScreen
                title="session-site"
              />
            </div>
            <div className="site-toolbar">
              <button className="site-btn" onClick={handleRefresh} title="刷新">刷新</button>
              <button className="site-btn" onClick={handleFullscreen} title="全屏">
                {isFullscreen ? "退出全屏" : "全屏"}
              </button>
              <button className="site-btn" onClick={handleNewTab} title="新标签页打开">新标签页</button>
              <button className="site-btn" onClick={handleDownloadZip} title="下载整站 zip">下载</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
