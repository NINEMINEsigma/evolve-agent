interface SessionLockOverlayProps {
  onRetry: () => void;
}

export default function SessionLockOverlay({ onRetry }: SessionLockOverlayProps) {
  return (
    <div className="session-lock-overlay">
      <div className="session-lock-content">
        <div className="session-lock-icon">🔒</div>
        <h2 className="session-lock-title">此会话已在其他标签页打开</h2>
        <p className="session-lock-desc">
          同一会话只能在一个标签页中活跃。请关闭其他标签页或切换到其他会话。
        </p>
        <button className="session-lock-retry-btn" onClick={onRetry}>
          重试
        </button>
      </div>
    </div>
  );
}