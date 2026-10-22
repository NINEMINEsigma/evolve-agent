import { useEffect } from "react";
import { usePersistentState } from "../../hooks/usePersistentState";
import { STORAGE_KEYS } from "../../constants/storage";
import { chatRuntimeController } from "../chat/chatRuntimeController";
import { useChatRuntimeStore } from "../chat/chatRuntimeStore";
import type { TabRenderContext } from "./registry";
import labels from "./resourceCleanupLabels.json";
import { stopSessionShell } from "../../services/shellResourcesApi";

/**
 * Resources tab: session resources, Shell sessions, Cron tasks and dynamic
 * endpoints. Migrated from the old resource drawer; lazy loading keys off the
 * active tab instead of the removed `open` prop.
 */
export default function ResourcesTab({ ctx }: { ctx: TabRenderContext }) {
  const { ws, activeTab } = ctx;
  const [resourcesExpanded, setResourcesExpanded] = usePersistentState(STORAGE_KEYS.DRAWER_RESOURCES_EXPANDED, true);
  const [backgroundExpanded, setBackgroundExpanded] = usePersistentState(STORAGE_KEYS.DRAWER_BACKGROUND_EXPANDED, true);
  const [cronExpanded, setCronExpanded] = usePersistentState(STORAGE_KEYS.DRAWER_CRON_EXPANDED, true);
  const [dynamicEndpointsExpanded, setDynamicEndpointsExpanded] = usePersistentState(STORAGE_KEYS.DRAWER_DYNENDPOINTS_EXPANDED, true);

  const resources = useChatRuntimeStore((state) => state.resources);
  const resourcesLoading = useChatRuntimeStore((state) => state.resourcesLoading);
  const resourcesError = useChatRuntimeStore((state) => state.resourcesError);
  const images = resources?.images ?? [];
  const downloads = resources?.downloads ?? [];
  const sessionId = ctx.sessionId;

  useEffect(() => {
    if (activeTab === "resources" && resourcesExpanded) void chatRuntimeController.loadResources();
  }, [activeTab, resourcesExpanded, sessionId]);

  return (
    <div className="resources-tab" data-tour="resources-tab">
      <div className="tab-panel-safe-top" aria-hidden="true" />
      <div className="resources-tab-content">
        {/* Resources section */}
        <div className="drawer-section">
          <div className="drawer-section-header" onClick={() => setResourcesExpanded((v) => !v)}>
            <span className={`drawer-arrow ${resourcesExpanded ? "expanded" : ""}`}>▶</span>
            <span className="drawer-section-title">资源 ({images.length + downloads.length})</span>
          </div>
          {resourcesExpanded && (
            <div className="drawer-section-body">
              {resourcesLoading && <div className="drawer-empty">正在加载资源…</div>}
              {resourcesError && (
                <div className="drawer-empty">
                  加载失败：{resourcesError}
                  <button type="button" onClick={() => void chatRuntimeController.loadResources(true)}>重试</button>
                </div>
              )}
              {!resourcesLoading && !resourcesError && images.length === 0 && downloads.length === 0 && (
                <div className="drawer-empty">暂无资源</div>
              )}
              {images.length > 0 && (
                <div className="resource-group">
                  <div className="resource-group-title">图片 ({images.length})</div>
                  <div className="resource-grid">
                    {images.map((img) => (
                      <div key={img.resource_id} className="resource-img-card">
                        <img src={img.url} alt={img.alt} className="resource-img-thumb" onClick={() => ctx.setLightboxSrc(img.url)} />
                        <a href={img.url} download className="resource-download-link">下载</a>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {downloads.length > 0 && (
                <div className="resource-group">
                  <div className="resource-group-title">文件 ({downloads.length})</div>
                  {downloads.map((d) => (
                    <div key={d.resource_id} className="resource-download-card">
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

        {/* Shell sessions section */}
        <div className="drawer-section">
          <div className="drawer-section-header" onClick={() => setBackgroundExpanded((v) => !v)}>
            <span className={`drawer-arrow ${backgroundExpanded ? "expanded" : ""}`}>▶</span>
            <span className="drawer-section-title">Shell 会话 ({ws.shells.length})</span>
          </div>
          {backgroundExpanded && (
            <div className="drawer-section-body">
              {ws.shells.length === 0 ? (
                <div className="drawer-empty">暂无 Shell 会话</div>
              ) : (
                ws.shells.map((shell) => (
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
                    {shell.cleanup && !shell.cleanup.complete ? (
                      <div className="task-list-meta">{labels.cleanupPending}</div>
                    ) : null}
                    <div className="task-list-actions">
                      <button
                        className="task-list-action stop"
                        onClick={() => {
                          void stopSessionShell(sessionId, shell.shell_id).then((result) => {
                            if (result?.cleanup.complete) {
                              ws.setShells((previous) => previous.filter((item) => item.shell_id !== shell.shell_id));
                              return;
                            }
                            if (result) {
                              ws.setShells((previous) => previous.map((item) => (
                                item.shell_id === shell.shell_id ? result.shell : item
                              )));
                            }
                          });
                        }}
                      >{shell.cleanup && !shell.cleanup.complete ? labels.refreshStatus : "停止"}</button>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>

        {/* Cron tasks section */}
        <div className="drawer-section">
          <div className="drawer-section-header" onClick={() => setCronExpanded((v) => !v)}>
            <span className={`drawer-arrow ${cronExpanded ? "expanded" : ""}`}>▶</span>
            <span className="drawer-section-title">定时任务 ({ws.cronTasks.length})</span>
          </div>
          {cronExpanded && (
            <div className="drawer-section-body">
              {ws.cronTasks.length === 0 ? (
                <div className="drawer-empty">暂无定时任务</div>
              ) : (
                ws.cronTasks.map((t) => (
                  <div key={t.task_id} className={`cron-list-item ${t.should_schedule ? "active" : "inactive"}`}>
                    <div className="cron-list-header">
                      <span className="cron-list-name">{t.name}</span>
                      <span className={`cron-list-status ${t.should_schedule ? "active" : "inactive"}`}>{t.should_schedule ? "运行中" : "已停止"}</span>
                    </div>
                    <div className="cron-list-schedule">{t.schedule_type === "interval" ? `${t.schedule_value} 秒` : t.schedule_value}</div>
                    <div className="cron-list-meta">下次执行: {t.next_run ? new Date(t.next_run).toLocaleString() : "-"} | 已执行: {t.run_count} 次</div>
                    <div className="cron-list-actions">
                      <button className="cron-list-action trigger" onClick={() => fetch(`/api/sessions/${sessionId}/cron-tasks/${t.task_id}/trigger`, { method: "POST" }).then(() => ws.setCronTasks((prev) => prev.map((x) => x.task_id === t.task_id ? { ...x, run_count: x.run_count + 1 } : x)))}>立即触发</button>
                      <button className="cron-list-action cancel" onClick={() => fetch(`/api/sessions/${sessionId}/cron-tasks/${t.task_id}/cancel`, { method: "POST" }).then(() => ws.setCronTasks((prev) => prev.filter((x) => x.task_id !== t.task_id)))}>取消</button>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>

        {/* Dynamic endpoints section */}
        <div className="drawer-section">
          <div className="drawer-section-header" onClick={() => setDynamicEndpointsExpanded((v) => !v)}>
            <span className={`drawer-arrow ${dynamicEndpointsExpanded ? "expanded" : ""}`}>▶</span>
            <span className="drawer-section-title">动态端点 ({ws.dynamicEndpoints.length})</span>
          </div>
          {dynamicEndpointsExpanded && (
            <div className="drawer-section-body">
              {ws.dynamicEndpoints.length === 0 ? (
                <div className="drawer-empty">暂无动态端点</div>
              ) : (
                ws.dynamicEndpoints.map((ep) => (
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
    </div>
  );
}
