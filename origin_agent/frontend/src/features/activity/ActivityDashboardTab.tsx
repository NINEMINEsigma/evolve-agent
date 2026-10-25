import { useEffect, useState } from "react";
import type { TabRenderContext } from "../tabs/registry";
import ActivityCanvas from "./ActivityCanvas";
import { activityLabels } from "./labels";
import { useActivityDashboard } from "./useActivityDashboard";
import type { ActivityEvent } from "./types";

function formatTime(timestamp: string): string {
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? timestamp : date.toLocaleTimeString();
}

function eventDetail(event: ActivityEvent): string {
  const parts = [event.character_name, event.tool_name, event.stream_id, event.tool_call_id]
    .filter((value): value is string => Boolean(value));
  return parts.join(" · ");
}

function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return reduced;
}

function eventStatus(event: ActivityEvent | undefined): string {
  return event ? event.status.toUpperCase() : "WAITING";
}

export default function ActivityDashboardTab({ ctx }: { ctx: TabRenderContext }) {
  const active = ctx.activeTab === "activity";
  const dashboard = useActivityDashboard(active);
  const reducedMotion = useReducedMotion();
  const overview = dashboard.overview;
  const recentEvents = [...dashboard.events].reverse();
  const latestEvent = recentEvents[0];
  const observedTotal = dashboard.counts.events;
  const maxObserved = Math.max(1, observedTotal);

  return (
    <div className="activity-dashboard-tab">
      <header className="activity-dashboard-header">
        <div className="activity-kpi">
          <span>{activityLabels.kpi.sessions}</span>
          <strong>{overview?.session_count ?? "—"}</strong>
          <i />
        </div>
        <div className="activity-kpi">
          <span>{activityLabels.kpi.loops}</span>
          <strong>{overview?.active_loop_count ?? "—"}</strong>
          <i />
        </div>
        <div className="activity-kpi">
          <span>{activityLabels.kpi.tools}</span>
          <strong>{overview?.tool_count ?? "—"}</strong>
          <i />
        </div>
        <div className="activity-kpi">
          <span>{activityLabels.kpi.toolsets}</span>
          <strong>{overview?.toolset_count ?? "—"}</strong>
          <i />
        </div>
        <div className={`activity-connection activity-connection-${dashboard.connectionState}`}>
          <i /> {activityLabels.connection[dashboard.connectionState]}
        </div>
      </header>

      <main className="activity-dashboard-body">
        <section className="activity-stage-panel">
          <ActivityCanvas events={dashboard.events} reducedMotion={reducedMotion} />
          <div className="activity-console-badge">▣ CONSOLE</div>
          <div className="activity-stage-status">
            <strong>{dashboard.counts.events.toString().padStart(2, "0")} / {overview?.active_loop_count ?? "—"} LOOPS</strong>
            <span>{dashboard.counts.tools} TOOLS · {dashboard.gapCount} GAP</span>
          </div>
        </section>

        <section className="activity-bottom-data" aria-label="Activity log and statistics">
          <article className="activity-event-log">
            <div className="activity-bottom-heading">
              <h3>ACTIVITY LOG / INVESTIGATION FEED</h3>
              <span>{dashboard.gapCount > 0 ? `${activityLabels.events.gap} · ${dashboard.gapCount}` : "LIVE"}</span>
            </div>
            {dashboard.overviewError && (
              <div className="activity-log-notice">{activityLabels.overviewError}: {dashboard.overviewError}</div>
            )}
            {recentEvents.length === 0 ? (
              <div className="activity-event-empty">{activityLabels.empty}</div>
            ) : (
              <div className="activity-event-log-list">
                {recentEvents.slice(0, 18).map((event) => (
                  <div className={`activity-event-row activity-event-${event.kind}`} key={`${event.sequence}-${event.phase}`}>
                    <span className="activity-event-sequence">{String(event.sequence).padStart(3, "0")}</span>
                    <span className="activity-event-time">{formatTime(event.timestamp)}</span>
                    <b>{event.kind.replace("_", " ")}</b>
                    <span>{event.phase}</span>
                    <span>{event.status}</span>
                    <span className="activity-event-detail">{eventDetail(event) || event.session_id}</span>
                    <span className="activity-event-duration">{event.duration_ms === null ? "—" : `${event.duration_ms}ms`}</span>
                  </div>
                ))}
              </div>
            )}
          </article>

          <aside className="activity-stats-deck">
            <section className="activity-stats-card activity-stats-counts">
              <h3>OBSERVED SIGNALS</h3>
              <div><b>{dashboard.counts.messages.toString().padStart(2, "0")}</b><span>MESSAGES</span></div>
              <div><b>{dashboard.counts.responses.toString().padStart(2, "0")}</b><span>RESPONSES</span></div>
              <div><b>{dashboard.counts.tools.toString().padStart(2, "0")}</b><span>TOOLS</span></div>
            </section>

            <section className="activity-stats-card activity-stats-distribution">
              <h3>EVENT DISTRIBUTION</h3>
              {(["message_received", "agent_response", "tool_call"] as const).map((kind) => {
                const value = dashboard.events.filter((event) => event.kind === kind).length;
                return (
                  <div className="activity-stat-bar" key={kind}>
                    <span>{kind === "message_received" ? "MESSAGE" : kind === "agent_response" ? "RESPONSE" : "TOOL"}</span>
                    <i><b style={{ width: `${(value / maxObserved) * 100}%` }} /></i>
                    <strong>{value.toString().padStart(2, "0")}</strong>
                  </div>
                );
              })}
            </section>

            <section className="activity-stats-card activity-stats-overview">
              <h3>PROCESS SNAPSHOT</h3>
              <div><span>SESSIONS</span><b>{overview?.session_count ?? "—"}</b></div>
              <div><span>LOOPS</span><b>{overview?.active_loop_count ?? "—"}</b></div>
              <div><span>TOOLS</span><b>{overview?.tool_count ?? "—"}</b></div>
              <div><span>SETS</span><b>{overview?.toolset_count ?? "—"}</b></div>
            </section>

            <section className="activity-stats-card activity-stats-status">
              <h3>LINK STATUS</h3>
              <div><i className={`activity-status-dot activity-status-${dashboard.connectionState}`} /><b>{activityLabels.connection[dashboard.connectionState]}</b></div>
              <span>{latestEvent ? `${latestEvent.kind} / ${eventStatus(latestEvent)}` : "NO ACTIVE EVENT"}</span>
              <span>{dashboard.gapCount > 0 ? `${dashboard.gapCount} DROPPED` : "NO STREAM GAP"}</span>
            </section>
          </aside>
        </section>
      </main>
    </div>
  );
}
