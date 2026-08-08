import { useRef } from "react";

export default function IframeRenderer({
  src,
  style,
  className,
  ...props
}: React.IframeHTMLAttributes<HTMLIFrameElement>): JSX.Element {
  const iframeRef = useRef<HTMLIFrameElement>(null);

  const handleOpenInNewTab = () => {
    if (src) window.open(src, "_blank", "noopener,noreferrer");
  };

  const handleFullscreen = async () => {
    try {
      await iframeRef.current?.requestFullscreen();
    } catch {
      // 部分嵌入式 WebView 不支持 Fullscreen API，静默忽略
    }
  };

  const {
    width: userWidth,
    margin: userMargin,
    borderRadius: userBorderRadius,
    ...iframeUserStyle
  } = (style ?? {}) as React.CSSProperties;

  const wrapperStyle: React.CSSProperties = {
    width: userWidth ?? "100%",
    margin: userMargin ?? "6px 0",
    borderRadius: userBorderRadius ?? "12px",
  };

  const iframeStyle: React.CSSProperties = {
    height: "400px",
    border: "none",
    borderRadius: "12px",
    ...iframeUserStyle,
  };

  return (
    <div className="iframe-renderer-wrapper" style={wrapperStyle}>
      <iframe
        ref={iframeRef}
        src={src}
        className={className}
        style={iframeStyle}
        sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
        {...props}
      />
      <div className="iframe-toolbar">
        <button
          className="iframe-toolbar-btn"
          onClick={handleOpenInNewTab}
          title="在新标签页打开"
          type="button"
        >
          <svg
            viewBox="0 0 24 24"
            width="16"
            height="16"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
            <polyline points="15 3 21 3 21 9" />
            <line x1="10" y1="14" x2="21" y2="3" />
          </svg>
        </button>
        <button
          className="iframe-toolbar-btn"
          onClick={handleFullscreen}
          title="全屏"
          type="button"
        >
          <svg
            viewBox="0 0 24 24"
            width="16"
            height="16"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M8 3H5a2 2 0 0 0-2 2v3" />
            <path d="M21 8V5a2 2 0 0 0-2-2h-3" />
            <path d="M3 16v3a2 2 0 0 0 2 2h3" />
            <path d="M16 21h3a2 2 0 0 0 2-2v-3" />
          </svg>
        </button>
      </div>
    </div>
  );
}