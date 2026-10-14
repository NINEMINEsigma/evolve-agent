import { useEffect, useMemo, useState } from "react";
import type { ReactElement } from "react";
import VariableCard, { VariableIssues } from "../sessionVariables/VariableCard";
import { buildVariableGroups } from "../sessionVariables/presentation";
import { useTabData } from "./TabDataContext";
import type { VariableGroup } from "../sessionVariables/types";
import type { TabRenderContext } from "./registry";

function Group({ group, collapsed, toggle }: {
  group: VariableGroup;
  collapsed: ReadonlySet<string>;
  toggle: (path: string) => void;
}): ReactElement {
  const expanded = !collapsed.has(group.path);
  return <section className="session-variable-group">
    <button type="button" className="session-variable-group-heading" aria-expanded={expanded} onClick={() => toggle(group.path)}>
      <span aria-hidden="true">{expanded ? "▾" : "▸"}</span>
      <span>{group.name}</span>
      <code>{group.path}</code>
    </button>
    {expanded && <div className="session-variable-group-body">
      {group.children.map((child) => <Group key={child.path} group={child} collapsed={collapsed} toggle={toggle} />)}
      {group.entries.length > 0 && <div className="session-variable-grid">
        {group.entries.map((entry) => <VariableCard key={entry.id} entry={entry} />)}
      </div>}
    </div>}
  </section>;
}

export default function VariablesTab({ ctx }: { ctx: TabRenderContext }): ReactElement {
  const { pool, loading, error, syncWarning, refresh } = useTabData().variables;
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const groups = useMemo(() => buildVariableGroups(pool?.variables ?? []), [pool]);
  useEffect(() => setCollapsed(new Set()), [ctx.sessionId]);
  const toggle = (path: string) => setCollapsed((previous) => {
    const next = new Set(previous);
    if (next.has(path)) next.delete(path); else next.add(path);
    return next;
  });

  return <div className="variables-tab">
    <div className="tab-panel-safe-top" aria-hidden="true" />
    <div className="variables-tab-content">
      <header className="session-variable-toolbar">
        <div><h2>会话变量</h2><span>{pool?.variables.length ?? 0} 个变量</span></div>
        <button type="button" onClick={() => void refresh()} disabled={loading || !ctx.sessionId}>{loading ? "正在刷新…" : "刷新"}</button>
      </header>
      <p className="session-variable-note">此 Tab 为只读。请在聊天中让主Agent创建或修改 JSON 变量及同级 .meta 配置。重新生成回复或删除消息不会回滚变量。</p>
      {ctx.currentSessionArchived && <p className="session-variable-note">当前会话已归档，显示的是该会话保留的变量文件。</p>}
      <code className="session-variable-root">{pool?.directory_path ?? `ws:sessions/${ctx.sessionId}/variables`}</code>
      {syncWarning && <div className="session-variable-warning" role="status">{syncWarning}</div>}
      {loading && !pool && <div className="session-variable-empty" role="status">正在读取会话变量池…</div>}
      {error && <div className="session-variable-warning" role="alert">读取失败：{error}{pool ? "。当前显示的上次数据可能已过期。" : ""}</div>}
      {pool && !pool.scan_complete && <div className="session-variable-warning" role="alert">目录扫描不完整，部分不受支持的路径没有读取。请查看问题并修复，不能将此结果视为完整游戏状态。</div>}
      {pool && pool.issues.length > 0 && <VariableIssues issues={pool.issues} />}
      {pool && pool.variables.length === 0 && <div className="session-variable-empty">
        {pool.root_exists ? "变量目录已存在，尚无可显示的变量。" : "尚未创建变量目录。"}
        <p>主Agent可在此目录中创建数字或字符串的 JSON 文件，并按角色或城市放入子目录。</p>
      </div>}
      {groups.map((group) => <Group key={group.path} group={group} collapsed={collapsed} toggle={toggle} />)}
    </div>
  </div>;
}
