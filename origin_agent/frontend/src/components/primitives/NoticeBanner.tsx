import type { OperationNotice } from "../../types";

interface NoticeBannerProps {
  notice: OperationNotice | null;
  onDismiss: () => void;
}

export default function NoticeBanner({ notice, onDismiss }: NoticeBannerProps) {
  if (!notice) return null;

  return (
    <div className={`notice-banner notice-banner-${notice.kind}`} role="alert">
      <span className="notice-banner-message">{notice.message}</span>
      <button
        type="button"
        className="notice-banner-close"
        onClick={onDismiss}
        aria-label="关闭通知"
      >
        ×
      </button>
    </div>
  );
}
