import { useEffect, useState } from "react";

export interface SessionIdentityProps {
  title: string;
  sessionId: string;
}

type CopyState = "idle" | "copied" | "failed";

export default function SessionIdentity({ title, sessionId }: SessionIdentityProps) {
  const [copyState, setCopyState] = useState<CopyState>("idle");

  useEffect(() => {
    if (copyState === "idle") return;
    const timer = window.setTimeout(() => setCopyState("idle"), 1400);
    return () => window.clearTimeout(timer);
  }, [copyState]);

  const handleCopy = async () => {
    if (!sessionId) return;
    try {
      await navigator.clipboard.writeText(sessionId);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  };

  const tooltip = copyState === "copied"
    ? "会话 ID 已复制"
    : copyState === "failed"
      ? "会话 ID 复制失败，请检查浏览器剪贴板权限"
      : sessionId
        ? `点击复制会话 ID：${sessionId}`
        : "当前没有会话";

  return (
    <button
      type="button"
      className={`session-identity session-identity--${copyState}`}
      disabled={!sessionId}
      onClick={() => void handleCopy()}
      data-tooltip={tooltip}
      aria-label={sessionId ? `复制会话 ID：${sessionId}` : title}
    >
      <span className="session-identity-title">{title}</span>
      <span className="session-identity-id">{sessionId || title}</span>
    </button>
  );
}
