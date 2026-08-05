import { useEffect } from "react";
import type { ClipboardDisplay } from "../types";
import { TIMING } from "../constants/timing";

// 密钥展示横幅：fixed 顶部居中，60 秒自动消失，点击复制后立即消失。
// 与常驻 ClipboardPanel 无关 —— 一次性展示，不进入面板、不落盘。

interface SecretBannerProps {
  banner: ClipboardDisplay | null;
  onDismiss: () => void;
}

export default function SecretBanner({ banner, onDismiss }: SecretBannerProps) {
  // banner 变化时重置定时器；复制成功/关闭按钮/超时都会触发 onDismiss
  useEffect(() => {
    if (!banner) return;
    const timer = setTimeout(onDismiss, TIMING.BANNER_TTL);
    return () => clearTimeout(timer);
  }, [banner, onDismiss]);

  if (!banner) return null;

  return (
    <div className="secret-banner">
      <div className="secret-banner-header">
        <span className="secret-banner-label">{banner.label}</span>
        <button
          className="secret-banner-close"
          onClick={onDismiss}
          aria-label="关闭"
        >
          ×
        </button>
      </div>
      <pre className="secret-banner-content">{banner.content}</pre>
      <button
        className="secret-banner-copy"
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
    </div>
  );
}