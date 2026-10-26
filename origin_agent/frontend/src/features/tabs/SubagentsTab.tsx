import { SubagentCard } from "../../components/SubagentCard";
import { SID_DISPLAY_LEN } from "../../constants/session";
import SubagentAvatar from "../characterAvatars/SubagentAvatar";
import type { TabRenderContext } from "./registry";

/**
 * Subagents tab: one top-level tab holding an inner tab row for each
 * subagent session. Migrated from SubagentPanel; the open/close semantics
 * moved to the tab system, so the collapse button is gone.
 */
export default function SubagentsTab({ ctx }: { ctx: TabRenderContext }) {
  const { ws, activeSubagentId, setActiveSubagentId } = ctx;
  const subagentSessions = ws.subagentSessions;
  const items = Object.values(subagentSessions);

  const resolvedActiveId =
    activeSubagentId && subagentSessions[activeSubagentId]
      ? activeSubagentId
      : (items[0]?.session_id ?? null);
  const activeSession = resolvedActiveId
    ? subagentSessions[resolvedActiveId]
    : null;

  return (
    <div className="subagents-tab">
            <div className="subagents-tab-content">
        <div className="subagent-panel-header">
          <div className="subagent-tabs">
            {items.map((s) => (
              <button
                key={s.session_id}
                type="button"
                className={`subagent-tab ${s.session_id === resolvedActiveId ? "active" : ""}`}
                onClick={() => setActiveSubagentId(s.session_id)}
                title={s.name || s.session_id}
              >
                <span className="subagent-tab-name">
                  <SubagentAvatar name={s.name || s.session_id} />
                  {s.name || s.session_id.slice(0, SID_DISPLAY_LEN)}
                </span>
                <span className={`subagent-tab-status subagent-status-${s.status}`} />
              </button>
            ))}
          </div>
        </div>
        <div className="subagent-panel-body">
          {activeSession ? (
            <SubagentCard
              key={resolvedActiveId}
              session={activeSession}
              collapsed={false}
              onToggleCollapse={() => {}}
              disableToggle
            />
          ) : (
            <div className="drawer-empty">暂无子会话</div>
          )}
        </div>
      </div>
    </div>
  );
}
