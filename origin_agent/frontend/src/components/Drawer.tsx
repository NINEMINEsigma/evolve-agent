import { useState } from "react";
import { ChatMessage, CronTask } from "../types";
import { extractMessageResources } from "../utils";

interface DrawerProps {
  open: boolean;
  onClose: () => void;
  sessionId: string;
  messages: ChatMessage[];
  onImageClick: (src: string) => void;
  bgTasks: Array<{
    task_id: string; pid: number; command: string[]; start_time: number; log_path: string; status: string
  }>;
  setBgTasks: React.Dispatch<React.SetStateAction<Array<{
    task_id: string; pid: number; command: string[]; start_time: number; log_path: string; status: string
  }>>>;
  cronTasks: CronTask[];
  setCronTasks: React.Dispatch<React.SetStateAction<CronTask[]>>;
}

export default function Drawer({
  open, onClose, sessionId, messages, onImageClick,
  bgTasks, setBgTasks, cronTasks, setCronTasks,
}: DrawerProps) {
  const [resourcesExpanded, setResourcesExpanded] = useState(true);
  const [backgroundExpanded, setBackgroundExpanded] = useState(true);
  const [cronExpanded, setCronExpanded] = useState(true);

  const { images, audios, downloads } = extractMessageResources(messages);

  if (!open) return null;

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer-panel" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-header">
          <span className="drawer-title">会话资源 / 任务</span>
          <button className="drawer-close" onClick={onClose}>✕</button>
        </div>
        <div className="drawer-body">
          {/* 资源区块 */}
          <div className="drawer-section">
            <div className="drawer-section-header" onClick={() => setResourcesExpanded((v) => !v)}>
              <span className={`drawer-arrow ${resourcesExpanded ? "expanded" : ""}`}>▶</span>
              <span className="drawer-section-title">资源 ({images.length + audios.length + downloads.length})</span>
            </div>
            {resourcesExpanded && (
              <div className="drawer-section-body">
                {images.length === 0 && audios.length === 0 && downloads.length === 0 && (
                  <div className="drawer-empty">暂无资源</div>
                )}
                {images.length > 0 && (
                  <div className="resource-group">
                    <div className="resource-group-title">图片 ({images.length})</div>
                    <div className="resource-grid">
                      {images.map((img) => (
                        <div key={img.id} className="resource-img-card">
                          <img src={img.src} alt={img.alt} className="resource-img-thumb" onClick={() => onImageClick(img.src)} />
                          <a href={img.src} download className="resource-download-link">下载</a>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {audios.length > 0 && (
                  <div className="resource-group">
                    <div className="resource-group-title">音频 ({audios.length})</div>
                    {audios.map((a) => (
                      <div key={a.id} className="resource-audio-card">
                        <audio controls src={a.url} className="resource-audio-player" />
                        <a href={a.url} download className="resource-download-link">下载</a>
                      </div>
                    ))}
                  </div>
                )}
                {downloads.length > 0 && (
                  <div className="resource-group">
                    <div className="resource-group-title">文件 ({downloads.length})</div>
                    {downloads.map((d) => (
                      <div key={d.id} className="resource-download-card">
                        <span className="resource-filename">{d.filename}</span>
                        {d.size != null && <span className="resource-filesize">（{(d.size / 1024).toFixed(1)} KB）</span>}
                        <a href={d.url} download={d.filename} className="resource-download-link">下载</a>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* 后台任务区块 */}
          <div className="drawer-section">
            <div className="drawer-section-header" onClick={() => setBackgroundExpanded((v) => !v)}>
              <span className={`drawer-arrow ${backgroundExpanded ? "expanded" : ""}`}>▶</span>
              <span className="drawer-section-title">后台任务 ({bgTasks.length})</span>
            </div>
            {backgroundExpanded && (
              <div className="drawer-section-body">
                {bgTasks.length === 0 ? (
                  <div className="drawer-empty">暂无后台任务</div>
                ) : (
                  bgTasks.map((t) => (
                    <div key={t.task_id} className={`task-list-item ${t.status === "running" ? "running" : "stopped"}`}>
                      <div className="task-list-header">
                        <span className="task-list-name">{t.command.join(" ")}</span>
                        <span className={`task-list-status status-${t.status}`}>{t.status}</span>
                      </div>
                      <div className="task-list-meta">PID: {t.pid} | 启动: {new Date(t.start_time * 1000).toLocaleString()}</div>
                      <div className="task-list-actions">
                        <button className="task-list-action stop" onClick={() => fetch(`/api/sessions/${sessionId}/background-tasks/${t.task_id}/stop`, { method: "POST" }).then(() => setBgTasks((prev) => prev.map((x) => x.task_id === t.task_id ? { ...x, status: "stopping" } : x)))}>停止</button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>

          {/* 定时任务区块 */}
          <div className="drawer-section">
            <div className="drawer-section-header" onClick={() => setCronExpanded((v) => !v)}>
              <span className={`drawer-arrow ${cronExpanded ? "expanded" : ""}`}>▶</span>
              <span className="drawer-section-title">定时任务 ({cronTasks.length})</span>
            </div>
            {cronExpanded && (
              <div className="drawer-section-body">
                {cronTasks.length === 0 ? (
                  <div className="drawer-empty">暂无定时任务</div>
                ) : (
                  cronTasks.map((t) => (
                    <div key={t.task_id} className={`cron-list-item ${t.should_schedule ? "active" : "inactive"}`}>
                      <div className="cron-list-header">
                        <span className="cron-list-name">{t.name}</span>
                        <span className={`cron-list-status ${t.should_schedule ? "active" : "inactive"}`}>{t.should_schedule ? "运行中" : "已停止"}</span>
                      </div>
                      <div className="cron-list-schedule">{t.schedule_type === "interval" ? `每 ${t.schedule_value} 秒` : t.schedule_value}</div>
                      <div className="cron-list-meta">下次执行: {t.next_run ? new Date(t.next_run).toLocaleString() : "-"} | 已执行: {t.run_count} 次</div>
                      <div className="cron-list-actions">
                        <button className="cron-list-action trigger" onClick={() => fetch(`/api/sessions/${sessionId}/cron-tasks/${t.task_id}/trigger`, { method: "POST" }).then(() => setCronTasks((prev) => prev.map((x) => x.task_id === t.task_id ? { ...x, run_count: x.run_count + 1 } : x)))}>立即触发</button>
                        <button className="cron-list-action cancel" onClick={() => fetch(`/api/sessions/${sessionId}/cron-tasks/${t.task_id}/cancel`, { method: "POST" }).then(() => setCronTasks((prev) => prev.filter((x) => x.task_id !== t.task_id)))}>取消</button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}