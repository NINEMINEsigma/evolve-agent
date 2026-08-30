import { useEffect } from "react";
import type { ClipboardDisplay } from "../../types";
import { TIMING } from "../../constants/timing";

// 一次性可复制横幅基元：fixed 顶部居中，TTL 自动消失，复制成功/关闭按钮触发 onDismiss。
// 不进常驻 ClipboardPanel —— 一次性展示，不进入面板、不落盘。

interface CopyBannerProps {
  banner: ClipboardDisplay | null;
  onDismiss: () => void;
}

export default function CopyBanner({ banner, onDismiss }: CopyBannerProps) {
  // banner 变化时重置定时器；复制成功/关闭按钮/超时都会触发 onDismiss
  useEffect(() => {
    if (!banner) return;
    const timer = setTimeout(onDismiss, TIMING.BANNER_TTL);
    return () => clearTimeout(timer);
  }, [banner, onDismiss]);

  if (!banner) return null;

  return (
    <div className="copy-banner">
      <div className="copy-banner-header">
        <span className="copy-banner-label">{banner.label}</span>
        <button
          className="copy-banner-close"
          onClick={onDismiss}
          aria-label="关闭"
        >
          ×
        </button>
      </div>
      <pre className="copy-banner-content">{banner.content}</pre>
      <button
        className="copy-banner-copy"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(banner.content);
            onDismiss();
          } catch {
            // 剪贴板写入失败时保留横幅，允许用户手动选中复制
          }
        }}
      >
        复制
      </button>
      <div
        key={banner.display_id}
        className="copy-banner-progress"
        style={{ animationDuration: `${TIMING.BANNER_TTL}ms` }}
      />
    </div>
  );
}