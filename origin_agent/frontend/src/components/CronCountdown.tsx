import { useEffect, useMemo, useState } from "react";
import type { CronTask } from "../types";
import { TIMING } from "../constants/timing";

function formatCountdown(ms: number) {
  const seconds = Math.max(0, Math.ceil(ms / 1000));
  return `${seconds}s`;
}

export default function CronCountdown({ cronTasks }: { cronTasks: CronTask[] }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), TIMING.CRON_TICK);
    return () => window.clearInterval(timer);
  }, []);

  const nextTask = useMemo(() => {
    return cronTasks
      .filter((task) => task.should_schedule && task.next_run)
      .map((task) => ({ task, nextAt: new Date(task.next_run as string).getTime() }))
      .filter(({ nextAt }) => Number.isFinite(nextAt))
      .sort((a, b) => a.nextAt - b.nextAt)[0];
  }, [cronTasks]);

  if (!nextTask) return null;

  const remainingMs = nextTask.nextAt - now;
  if (remainingMs <= 0 || remainingMs > TIMING.CRON_WINDOW) return null;

  const remainingPercent = Math.max(0, Math.min(100, (remainingMs / TIMING.CRON_WINDOW) * 100));
  const taskName = nextTask.task.name || nextTask.task.task_id;

  return (
    <div className="cron-countdown-strip" aria-label="当前会话定时任务倒计时">
      <div className="cron-countdown-strip-fill" style={{ width: `${remainingPercent}%` }} />
      <div className="cron-countdown-tooltip">
        {taskName} · 剩余 {formatCountdown(remainingMs)}
      </div>
    </div>
  );
}