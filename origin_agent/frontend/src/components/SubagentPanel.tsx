import { useState, useEffect } from "react";
import { SubagentCard } from "./SubagentDrawer";
import { SubagentSession } from "../types";

interface SubagentPanelProps {
  open: boolean;
  onToggle: () => void;
  subagentSessions: Record<string, SubagentSession>;
  activeId: string | null;
  onSelect: (id: string) => void;
}

export default function SubagentPanel({
  open,
  onToggle,
  subagentSessions,
  activeId,
  onSelect,
}: SubagentPanelProps) {
  const items = Object.values(subagentSessions);
  const [openTick, setOpenTick] = useState(0);

  useEffect(() => {
    if (open) setOpenTick((t) => t + 1);
  }, [open]);

  if (!open) {
    return null;
  }

  const resolvedActiveId =
    activeId && subagentSessions[activeId]
      ? activeId
      : (items[0]?.session_id ?? null);
  const activeSession = resolvedActiveId
    ? subagentSessions[resolvedActiveId]
    : null;

  return (
    <div className="subagent-panel">
      <div className="subagent-panel-header">
        <div className="subagent-tabs">
          {items.map((s) => (
            <button
              key={s.session_id}
              className={`subagent-tab ${s.session_id === resolvedActiveId ? "active" : ""}`}
              onClick={() => onSelect(s.session_id)}
              title={s.name || s.session_id}
            >
              <span className="subagent-tab-name">
                {s.name || s.session_id.slice(0, 12)}
              </span>
              <span className={`subagent-tab-status subagent-status-${s.status}`} />
            </button>
          ))}
        </div>
        <button
          className="subagent-panel-collapse"
          onClick={onToggle}
          data-tooltip="收起子会话面板"
        >
          ▶
        </button>
      </div>
      <div className="subagent-panel-body">
        {activeSession ? (
          <SubagentCard
            key={resolvedActiveId}
            session={activeSession}
            collapsed={false}
            onToggleCollapse={() => {}}
            disableToggle
            openTick={openTick}
          />
        ) : (
          <div className="drawer-empty">暂无子会话</div>
        )}
      </div>
    </div>
  );
}