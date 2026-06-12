import { TaskProgress } from "../types";

interface TaskProgressPanelProps {
  taskProgress: Record<string, TaskProgress>;
  collapsed: boolean;
  onToggleCollapse: () => void;
}

export default function TaskProgressPanel({
  taskProgress,
  collapsed,
  onToggleCollapse,
}: TaskProgressPanelProps) {
  const keys = Object.keys(taskProgress);
  if (keys.length === 0) return null;

  return (
    <div className={`task-progress-panel ${collapsed ? "collapsed" : ""}`}>
      <div className="panel-header" onClick={onToggleCollapse}>
        <span className="panel-header-title">任务进度 ({keys.length})</span>
        <button className="panel-header-toggle">
          {collapsed ? "▼" : "▲"}
        </button>
      </div>
      {!collapsed && Object.values(taskProgress).map((tp) => (
        <div key={tp.task_id} className="task-progress-item">
          <div className="task-progress-header">
            <span className="task-progress-label">{tp.label}</span>
            <span className="task-progress-status">{tp.status}</span>
            <span className="task-progress-percent">{tp.percent}%</span>
          </div>
          <div className="task-progress-bar-bg">
            <div
              className="task-progress-bar-fill"
              style={{ width: `${tp.percent}%` }}
            />
          </div>
          <div className="task-progress-detail">
            {tp.current} / {tp.total}
          </div>
        </div>
      ))}
    </div>
  );
}