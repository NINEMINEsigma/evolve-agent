import { useMemo, useState } from "react";
import type { ReactElement } from "react";
import { fileChangesLabels as L, formatFileChangesLabel } from "../sessionFileChanges/labels";
import { buildFileChangeTree, type FileChangeTreeNode } from "../sessionFileChanges/tree";
import type {
  SessionFileChangeActorDto, SessionFileChangeEntryDto,
} from "../sessionFileChanges/types";
import type { TabRenderContext } from "./registry";

function formatOperatedAt(value: string): string {
  return new Date(value).toLocaleString();
}

function actorTexts(actors: readonly SessionFileChangeActorDto[]): string[] {
  const nameCounts = new Map<string, number>();
  for (const actor of actors) nameCounts.set(actor.character_name, (nameCounts.get(actor.character_name) ?? 0) + 1);
  return actors.map((actor) => (nameCounts.get(actor.character_name) ?? 0) > 1
    ? formatFileChangesLabel(L.actorDisambiguated, { name: actor.character_name, session: actor.session_id })
    : actor.character_name);
}

function EntryMeta({ entry }: { entry: SessionFileChangeEntryDto }): ReactElement {
  const transfer = entry.source_path !== null && entry.destination_path !== null;
  return <span className="file-changes-entry-meta">
    <span>{entry.operation_count}</span>
    <span>{actorTexts(entry.actors).join(L.actorSeparator)}</span>
    <time dateTime={entry.last_operated_at} title={entry.last_operated_at}>{formatOperatedAt(entry.last_operated_at)}</time>
    {transfer && <span title={L.moveTooltip}>{entry.source_path} → {entry.destination_path}</span>}
  </span>;
}

function FileNode({ entry, name }: { entry: SessionFileChangeEntryDto; name: string }): ReactElement {
  return <div
    className={`file-changes-file file-changes-file-${entry.display_state}`}
    data-file-change-state={entry.display_state}
    role="treeitem"
    aria-level={1}
    title={entry.path}
  >
    <span className="file-changes-file-icon" aria-hidden="true">•</span>
    <code className="file-changes-path">{name}</code>
    <span className="file-changes-operation" data-tooltip={entry.last_operation === "move" ? L.moveTooltip : undefined}>
      {L.operations[entry.last_operation]}
    </span>
    <span className="file-changes-state-badge">{L.states[entry.display_state]}</span>
    <EntryMeta entry={entry} />
  </div>;
}

function TreeNode({ node, depth }: { node: FileChangeTreeNode; depth: number }): ReactElement {
  const [expanded, setExpanded] = useState(true);
  const entry = node.entry;
  if (!node.directory && entry !== null) {
    return <div style={{ paddingLeft: depth * 18 }}><FileNode entry={entry} name={node.name} /></div>;
  }
  return <div className="file-changes-tree-node">
    <button
      type="button"
      className={`file-changes-folder${entry ? ` file-changes-file-${entry.display_state}` : ""}`}
      style={{ paddingLeft: depth * 18 }}
      aria-expanded={expanded}
      onClick={() => setExpanded((value) => !value)}
      title={node.path}
    >
      <span className="file-changes-folder-chevron" aria-hidden="true">{expanded ? "▾" : "▸"}</span>
      <span className="file-changes-folder-icon" aria-hidden="true">▰</span>
      <span className="file-changes-folder-name">{node.name}</span>
      {entry && <>
        <span className="file-changes-operation" data-tooltip={entry.last_operation === "move" ? L.moveTooltip : undefined}>
          {L.operations[entry.last_operation]}
        </span>
        <span className="file-changes-state-badge">{L.states[entry.display_state]}</span>
        <EntryMeta entry={entry} />
      </>}
    </button>
    {expanded && <div role="group">
      {node.children.map((child) => <TreeNode key={child.key} node={child} depth={depth + 1} />)}
    </div>}
  </div>;
}

export default function FileChangesTab({ ctx }: { ctx: TabRenderContext }): ReactElement {
  const state = ctx.fileChanges;
  const { summary, summaryStatus, summaryError, treeEntries, treeStatus, treeError, treeStale, refresh } = state;
  const tree = useMemo(() => buildFileChangeTree(treeEntries ?? []), [treeEntries]);
  const refreshing = summaryStatus === "refreshing" || summaryStatus === "loading"
    || treeStatus === "refreshing" || treeStatus === "loading";
  const visibleCount = summary === null ? 0 : summary.file_count + summary.directory_count;

  return <div className="file-changes-tab">
    <div className="tab-panel-safe-top" aria-hidden="true" />
    <div className="file-changes-content">
      <header className="file-changes-toolbar">
        <div className="file-changes-heading">
          <h2>{L.title}</h2>
          {summary !== null && <div className="file-changes-stats">
            <span className="file-changes-stat"><strong>{summary.file_count}</strong><span>{L.summaryFiles}</span></span>
            <span className="file-changes-stat"><strong>{summary.directory_count}</strong><span>{L.summaryDirectories}</span></span>
            <span className="file-changes-stat" data-tooltip={L.summaryOperationsTooltip}>
              <strong>{summary.operation_count}</strong><span>{L.summaryOperations}</span>
            </span>
          </div>}
        </div>
        <button type="button" className="file-changes-refresh" onClick={() => void refresh()}
          disabled={!ctx.sessionId || refreshing} aria-label={L.refresh}>
          {refreshing ? L.refreshing : L.refresh}
        </button>
      </header>

      {ctx.currentSessionArchived && <p className="file-changes-note">{L.archived}</p>}
      {summaryStatus === "error" && summary === null && <div className="file-changes-state is-error" role="alert">
        {summaryError ?? L.summaryReadFailed}
      </div>}
      {summaryStatus === "error" && summary !== null && <div className="file-changes-warning" role="status">
        {summaryError ?? L.summaryReadFailed} {L.stale}
      </div>}
      {treeStale && treeEntries !== null && <div className="file-changes-warning" role="status">
        {treeError ?? L.stale}
      </div>}
      {summary === null && summaryStatus !== "error" && <div className="file-changes-state" role="status">{L.loading}</div>}
      {summary !== null && visibleCount === 0 && <div className="file-changes-state">{L.empty}</div>}
      {summary !== null && visibleCount > 0 && treeEntries === null && treeStatus !== "error" && (
        <div className="file-changes-state" role="status">{L.treeLoading}</div>
      )}
      {summary !== null && visibleCount > 0 && treeStatus === "error" && treeEntries === null && (
        <div className="file-changes-state is-error" role="alert">{treeError ?? L.treeReadFailed}</div>
      )}
      {summary !== null && visibleCount > 0 && treeEntries !== null && tree.length > 0 && (
        <div className="file-changes-tree" role="tree" aria-label={L.treeLabel}>
          {tree.map((node) => <TreeNode key={node.key} node={node} depth={0} />)}
        </div>
      )}
    </div>
  </div>;
}
