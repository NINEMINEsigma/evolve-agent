import { TaskProgress } from "../types";

interface TaskProgressPanelProps {
  taskProgress: Record<string, TaskProgress>;
  collapsed: boolean;
  onToggleCollapse: () => void;
}

export default function TaskProgressPanel({
  taskProgress,
}: TaskProgressPanelProps) {
  const items = Object.values(taskProgress);
  if (items.length === 0) return null;

  return (
    <div className="task-progress-strip-panel" aria-label="任务进度">
      {items.map((tp) => (
        <div key={tp.task_id} className="task-progress-strip-item">
          <div
            className="task-progress-strip-fill"
            style={{ width: `${Math.max(0, Math.min(100, tp.percent))}%` }}
          />
          <div className="task-progress-tooltip">
            <div className="task-progress-tooltip-title">{tp.label}</div>
            <div className="task-progress-tooltip-meta">
              {tp.status} · {tp.percent}% · {tp.current} / {tp.total}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}