import { ChatMessage, CronTask, DynamicEndpoint, ShellInfo } from "../types";
import { extractMessageResources } from "../utils";
import { usePersistentState } from "../hooks/usePersistentState";
import { STORAGE_KEYS } from "../constants/storage";

interface DrawerProps {
  open: boolean;
  onClose: () => void;
  sessionId: string;
  messages: ChatMessage[];
  onImageClick: (src: string) => void;
  shells: ShellInfo[];
  setShells: React.Dispatch<React.SetStateAction<ShellInfo[]>>;
  cronTasks: CronTask[];
  setCronTasks: React.Dispatch<React.SetStateAction<CronTask[]>>;
  dynamicEndpoints: DynamicEndpoint[];
  width?: number;
  isResizing?: boolean;
  onResizePointerDown?: (e: React.PointerEvent<HTMLElement>) => void;
}

export default function Drawer({
  open, onClose, sessionId, messages, onImageClick,
  shells, setShells, cronTasks, setCronTasks, dynamicEndpoints,
  width, isResizing, onResizePointerDown,
}: DrawerProps) {
  const [resourcesExpanded, setResourcesExpanded] = usePersistentState(STORAGE_KEYS.DRAWER_RESOURCES_EXPANDED, true);
  const [backgroundExpanded, setBackgroundExpanded] = usePersistentState(STORAGE_KEYS.DRAWER_BACKGROUND_EXPANDED, true);
  const [cronExpanded, setCronExpanded] = usePersistentState(STORAGE_KEYS.DRAWER_CRON_EXPANDED, true);
  const [dynamicEndpointsExpanded, setDynamicEndpointsExpanded] = usePersistentState(STORAGE_KEYS.DRAWER_DYNENDPOINTS_EXPANDED, true);

  const { images, downloads } = extractMessageResources(messages);

  if (!open) return null;

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer-panel" data-tour="resource-drawer" style={width != null ? { width } : undefined} onClick={(e) => e.stopPropagation()}>
        <div className="drawer-header">
          <span className="drawer-title">会话资源 / 任务</span>
          <button className="drawer-close" onClick={onClose}>✕</button>
        </div>
        <div className="drawer-body">
          {/* 资源区块 */}
          <div className="drawer-section">
            <div className="drawer-section-header" onClick={() => setResourcesExpanded((v) => !v)}>
              <span className={`drawer-arrow ${resourcesExpanded ? "expanded" : ""}`}>▶</span>
              <span className="drawer-section-title">资源 ({images.length + downloads.length})</span>
            </div>
            {resourcesExpanded && (
              <div className="drawer-section-body">
                {images.length === 0 && downloads.length === 0 && (
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

          {/* Shell会话区块 */}
          <div className="drawer-section">
            <div className="drawer-section-header" onClick={() => setBackgroundExpanded((v) => !v)}>
              <span className={`drawer-arrow ${backgroundExpanded ? "expanded" : ""}`}>▶</span>
              <span className="drawer-section-title">Shell 会话 ({shells.length})</span>
            </div>
            {backgroundExpanded && (
              <div className="drawer-section-body">
                {shells.length === 0 ? (
                  <div className="drawer-empty">暂无 Shell 会话</div>
                ) : (
                  shells.map((shell) => (
                    <div key={shell.shell_id} className={`task-list-item ${shell.running ? "running" : "stopped"}`}>
                      <div className="task-list-header">
                        <span className="task-list-name">{shell.shell_type} · {shell.shell_id}</span>
                        <span className={`task-list-status status-${shell.running ? "running" : "stopped"}`}>
                          {shell.running ? "running" : `exited${shell.termination ? ` · ${shell.termination}` : ""}${shell.exit_code == null ? "" : ` (${shell.exit_code})`}`}
                        </span>
                      </div>
                      <div className="task-list-meta">创建者: {shell.character_name} | PID: {shell.pid ?? "-"}</div>
                      <div className="task-list-meta">目录: {shell.cwd}</div>
                      <div className="task-list-meta">启动: {new Date(shell.started_at * 1000).toLocaleString()}</div>
                      <div className="task-list-meta">最近活动: {new Date(shell.last_activity_at * 1000).toLocaleString()}</div>
                      <div className="task-list-actions">
                        <button
                          className="task-list-action stop"
                          onClick={() => fetch(`/api/sessions/${sessionId}/shells/${shell.shell_id}/stop`, { method: "POST" })
                            .then((response) => {
                              if (!response.ok) throw new Error(`Stop Shell failed: ${response.status}`);
                              setShells((previous) => previous.filter((item) => item.shell_id !== shell.shell_id));
                            })
                            .catch(() => {})}
                        >停止</button>
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
                      <div className="cron-list-schedule">{t.schedule_type === "interval" ? `${t.schedule_value} 秒` : t.schedule_value}</div>
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

          {/* 动态端点区块 */}
          <div className="drawer-section">
            <div className="drawer-section-header" onClick={() => setDynamicEndpointsExpanded((v) => !v)}>
              <span className={`drawer-arrow ${dynamicEndpointsExpanded ? "expanded" : ""}`}>▶</span>
              <span className="drawer-section-title">动态端点 ({dynamicEndpoints.length})</span>
            </div>
            {dynamicEndpointsExpanded && (
              <div className="drawer-section-body">
                {dynamicEndpoints.length === 0 ? (
                  <div className="drawer-empty">暂无动态端点</div>
                ) : (
                  dynamicEndpoints.map((ep) => (
                    <div key={ep.name} className="task-list-item">
                      <div className="task-list-header">
                        <span className="task-list-name">{ep.name}</span>
                        <span className="task-list-status">{ep.agent_name}</span>
                      </div>
                      <div className="task-list-meta">创建: {new Date(ep.created_at * 1000).toLocaleString()}</div>
                      <div className="task-list-meta">{ep.url}</div>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        </div>
        {onResizePointerDown && (
          <div
            className={`drawer-resize-handle ${isResizing ? "dragging" : ""}`}
            onPointerDown={onResizePointerDown}
            data-tooltip="拖拽调整抽屉宽度"
          />
        )}
      </div>
    </div>
  );
}