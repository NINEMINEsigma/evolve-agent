import type { SubagentSession } from "../types";

interface SubagentCountdownProps {
  subagentSessions: Record<string, SubagentSession>;
  idleCountdown: number | null;
}

export default function SubagentCountdown({
  subagentSessions,
  idleCountdown,
}: SubagentCountdownProps) {
  const items = Object.values(subagentSessions);
  const runningCount = items.filter((s) => s.status === "running").length;

  if (runningCount === 0 || idleCountdown === null || idleCountdown <= 0) return null;
  if (idleCountdown > 30) return null;

  const percent = Math.max(0, Math.min(100, (idleCountdown / 30) * 100));

  return (
    <div className="cron-countdown-strip" aria-label="子会话空闲收集倒计时">
      <div
        className="cron-countdown-strip-fill"
        style={{ background: "#64d2ff", boxShadow: "0 0 8px rgba(100, 210, 255, 0.55)", width: `${percent}%` }}
      />
      <div className="cron-countdown-tooltip">
        子会话 · {runningCount} 活跃 · {idleCountdown}s 后收集
      </div>
    </div>
  );
}