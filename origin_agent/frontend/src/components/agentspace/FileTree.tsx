import { useMemo, useRef, useState } from "react";
import type {
  DirectoryStateMap,
  EntrySelection,
  FileEntry,
  FileLock,
  TrashEntry,
} from "../../types";
import PopupLayer from "../primitives/PopupLayer";
import { DIMENSIONS } from "../../constants/dimensions";
import {
  creationParentForSelection,
  isPathWithin,
  parentPath,
  sortEntries,
} from "../../utils/agentspacePath";
import {
  ChevronIcon,
  ConflictIcon,
  FileIcon,
  FolderIcon,
  LockIcon,
  TrashIcon,
} from "./TreeIcons";

export interface FileTreeProps {
  rootEntries: FileEntry[];
  directories: DirectoryStateMap;
  expandedPaths: Set<string>;
  selection: EntrySelection;
  activePath: string | null;
  locks: FileLock[];
  trashEntries: TrashEntry[];
  trashExpanded: boolean;
  onSelect(entry: FileEntry): void;
  onToggleDirectory(path: string): Promise<void>;
  onOpenFile(path: string): Promise<void>;
  onRequestCreate(kind: "file" | "dir", parentPath: string): void;
  onRequestRename(entry: FileEntry): void;
  onRequestTrash(entry: FileEntry): void;
  onToggleTrash(): void;
  onRestoreTrash(entryId: string): Promise<void>;
  onPurgeTrash(entryId: string): void;
  onEmptyTrash(): void;
}

interface VisibleNode {
  entry: FileEntry;
  depth: number;
}

function collectVisible(
  entries: FileEntry[],
  directories: DirectoryStateMap,
  expanded: Set<string>,
  depth = 0,
): VisibleNode[] {
  const result: VisibleNode[] = [];
  for (const entry of sortEntries(entries)) {
    result.push({ entry, depth });
    if (entry.kind === "dir" && expanded.has(entry.path)) {
      result.push(...collectVisible(
        directories[entry.path]?.entries || [],
        directories,
        expanded,
        depth + 1,
      ));
    }
  }
  return result;
}

function matchingLocks(locks: FileLock[], entry: FileEntry): FileLock[] {
  return locks.filter((lock) =>
    lock.path === entry.path
    || (lock.recursive && isPathWithin(entry.path, lock.path))
    || (entry.kind === "dir" && isPathWithin(lock.path, entry.path)),
  );
}

interface TreeNodeProps extends Omit<FileTreeProps, "rootEntries" | "trashEntries" | "trashExpanded" | "onToggleTrash" | "onRestoreTrash" | "onPurgeTrash" | "onEmptyTrash"> {
  entry: FileEntry;
  depth: number;
  visibleNodes: VisibleNode[];
  rowRefs: React.MutableRefObject<Map<string, HTMLDivElement>>;
}

function FileTreeNode(props: TreeNodeProps) {
  const {
    entry,
    depth,
    directories,
    expandedPaths,
    selection,
    activePath,
    locks,
    visibleNodes,
    rowRefs,
    onSelect,
    onToggleDirectory,
    onOpenFile,
    onRequestCreate,
    onRequestRename,
    onRequestTrash,
  } = props;
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const isDirectory = entry.kind === "dir";
  const expanded = isDirectory && expandedPaths.has(entry.path);
  const selected = selection?.path === entry.path;
  const active = activePath === entry.path;
  const entryLocks = matchingLocks(locks, entry);
  const locked = entryLocks.length > 0;
  const directory = directories[entry.path];

  const activate = () => {
    onSelect(entry);
    if (isDirectory) void onToggleDirectory(entry.path);
    else void onOpenFile(entry.path);
  };

  const focusNode = (target: VisibleNode | undefined) => {
    if (!target) return;
    onSelect(target.entry);
    requestAnimationFrame(() => rowRefs.current.get(target.entry.path)?.focus());
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const index = visibleNodes.findIndex((node) => node.entry.path === entry.path);
    if (event.key === "ArrowDown") {
      event.preventDefault();
      focusNode(visibleNodes[index + 1]);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      focusNode(visibleNodes[index - 1]);
    } else if (event.key === "ArrowRight" && isDirectory && !expanded) {
      event.preventDefault();
      void onToggleDirectory(entry.path);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      if (isDirectory && expanded) void onToggleDirectory(entry.path);
      else {
        const parent = parentPath(entry.path);
        focusNode(visibleNodes.find((node) => node.entry.path === parent));
      }
    } else if (event.key === "Enter") {
      event.preventDefault();
      activate();
    } else if (event.key === "F2" && !locked) {
      event.preventDefault();
      onRequestRename(entry);
    } else if (event.key === "Delete" && !locked) {
      event.preventDefault();
      onRequestTrash(entry);
    }
  };

  return (
    <div role="none">
      <div
        ref={(node) => {
          if (node) rowRefs.current.set(entry.path, node);
          else rowRefs.current.delete(entry.path);
        }}
        className={[
          "agentspace-file-item",
          selected ? "agentspace-file-item-selected" : "",
          active ? "agentspace-file-item-active" : "",
          locked ? "agentspace-file-item-locked" : "",
        ].filter(Boolean).join(" ")}
        style={{ paddingLeft: DIMENSIONS.TREE_INDENT + depth * DIMENSIONS.TREE_INDENT }}
        role="treeitem"
        aria-level={depth + 1}
        aria-expanded={isDirectory ? expanded : undefined}
        aria-selected={selected}
        aria-disabled={locked}
        tabIndex={selected || (!selection && depth === 0) ? 0 : -1}
        title={locked
          ? `${entry.path}（由 ${entryLocks.flatMap((lock) => lock.owners.map((owner) => owner.character_name)).join("、")} 使用中）`
          : entry.path}
        onClick={activate}
        onKeyDown={onKeyDown}
        onContextMenu={(event) => {
          event.preventDefault();
          onSelect(entry);
          setMenu({ x: event.clientX, y: event.clientY });
        }}
      >
        <span
          className="agentspace-chevron"
          onClick={(event) => {
            if (!isDirectory) return;
            event.stopPropagation();
            onSelect(entry);
            void onToggleDirectory(entry.path);
          }}
        >
          {isDirectory && <ChevronIcon open={expanded} />}
        </span>
        <span className={`agentspace-type-icon agentspace-type-${entry.kind}`}>
          {isDirectory ? <FolderIcon open={expanded} /> : <FileIcon />}
        </span>
        <span className="agentspace-file-name">{entry.name}</span>
        {directory?.loading && <span className="agentspace-tree-spinner" aria-label="正在加载" />}
        {locked && <span className="agentspace-row-state" aria-label="Agent 使用中"><LockIcon /></span>}
      </div>

      {expanded && (
        <div role="group">
          {directory?.error && (
            <div className="agentspace-tree-message" style={{ paddingLeft: (depth + 2) * DIMENSIONS.TREE_INDENT }}>
              {directory.error}
            </div>
          )}
          {!directory?.loading && !directory?.error && (directory?.entries.length || 0) === 0 && (
            <div className="agentspace-tree-message" style={{ paddingLeft: (depth + 2) * DIMENSIONS.TREE_INDENT }}>
              空文件夹
            </div>
          )}
          {sortEntries(directory?.entries || []).map((child) => (
            <FileTreeNode
              {...props}
              key={child.path}
              entry={child}
              depth={depth + 1}
            />
          ))}
        </div>
      )}

      {menu && (
        <PopupLayer
          position={menu}
          onClose={() => setMenu(null)}
          className="agentspace-context-menu"
        >
          {isDirectory && (
            <>
              <button className="agentspace-context-menu-item" disabled={locked} onClick={() => { onRequestCreate("file", entry.path); setMenu(null); }}>
                新建文件
              </button>
              <button className="agentspace-context-menu-item" disabled={locked} onClick={() => { onRequestCreate("dir", entry.path); setMenu(null); }}>
                新建文件夹
              </button>
            </>
          )}
          <button className="agentspace-context-menu-item" disabled={locked} onClick={() => { onRequestRename(entry); setMenu(null); }}>
            重命名
          </button>
          <button className="agentspace-context-menu-item agentspace-context-menu-danger" disabled={locked} onClick={() => { onRequestTrash(entry); setMenu(null); }}>
            移入垃圾桶
          </button>
        </PopupLayer>
      )}
    </div>
  );
}

function TrashTree({
  entries,
  expanded,
  onToggle,
  onRestore,
  onPurge,
  onEmpty,
}: {
  entries: TrashEntry[];
  expanded: boolean;
  onToggle(): void;
  onRestore(entryId: string): Promise<void>;
  onPurge(entryId: string): void;
  onEmpty(): void;
}) {
  const [menu, setMenu] = useState<{ x: number; y: number; entry: TrashEntry } | null>(null);
  return (
    <div className="agentspace-trash-section" role="none">
      <div
        className="agentspace-file-item agentspace-trash-root"
        role="treeitem"
        aria-expanded={expanded}
        tabIndex={-1}
        onClick={onToggle}
      >
        <span className="agentspace-chevron"><ChevronIcon open={expanded} /></span>
        <span className="agentspace-type-icon agentspace-type-trash"><TrashIcon /></span>
        <span className="agentspace-file-name">垃圾桶</span>
        <span className="agentspace-trash-count">{entries.length}</span>
        {entries.length > 0 && (
          <button
            className="agentspace-inline-action"
            title="清空垃圾桶"
            onClick={(event) => { event.stopPropagation(); onEmpty(); }}
          >
            清空
          </button>
        )}
      </div>
      {expanded && (
        <div role="group">
          {entries.length === 0 && <div className="agentspace-tree-message">垃圾桶为空</div>}
          {entries.map((entry) => (
            <div
              key={`${entry.entry_id}-${entry.state}`}
              className={`agentspace-trash-entry agentspace-trash-${entry.state}`}
              role="treeitem"
              tabIndex={-1}
              title={entry.error || entry.original_path || entry.entry_id}
              onContextMenu={(event) => {
                event.preventDefault();
                setMenu({ x: event.clientX, y: event.clientY, entry });
              }}
            >
              <span className="agentspace-chevron" />
              <span className="agentspace-type-icon">
                {entry.state === "corrupt" ? <ConflictIcon /> : <TrashIcon />}
              </span>
              <span className="agentspace-trash-label">
                <span>{entry.name || entry.entry_id}</span>
                <small>
                  {[entry.original_path || entry.error || "恢复条目", entry.deleted_at ? new Date(entry.deleted_at).toLocaleString() : ""].filter(Boolean).join(" · ")}
                </small>
              </span>
              <button className="agentspace-inline-action" disabled={entry.state === "corrupt"} onClick={() => void onRestore(entry.entry_id)}>
                恢复
              </button>
            </div>
          ))}
        </div>
      )}
      {menu && (
        <PopupLayer position={menu} onClose={() => setMenu(null)} className="agentspace-context-menu">
          <button className="agentspace-context-menu-item" disabled={menu.entry.state === "corrupt"} onClick={() => { void onRestore(menu.entry.entry_id); setMenu(null); }}>
            恢复
          </button>
          <button className="agentspace-context-menu-item agentspace-context-menu-danger" onClick={() => { onPurge(menu.entry.entry_id); setMenu(null); }}>
            永久删除
          </button>
        </PopupLayer>
      )}
    </div>
  );
}

export default function FileTree(props: FileTreeProps) {
  const rowRefs = useRef(new Map<string, HTMLDivElement>());
  const visibleNodes = useMemo(
    () => collectVisible(props.rootEntries, props.directories, props.expandedPaths),
    [props.rootEntries, props.directories, props.expandedPaths],
  );
  const createParent = creationParentForSelection(props.selection);

  return (
    <div className="agentspace-file-tree">
      <div className="agentspace-file-tree-toolbar">
        <button className="agentspace-toolbar-btn" title={`在 ${createParent || "根目录"} 新建文件`} onClick={() => props.onRequestCreate("file", createParent)}>
          + 文件
        </button>
        <button className="agentspace-toolbar-btn" title={`在 ${createParent || "根目录"} 新建文件夹`} onClick={() => props.onRequestCreate("dir", createParent)}>
          + 文件夹
        </button>
      </div>
      <div className="agentspace-file-tree-list" role="tree" aria-label="Agentspace 文件树">
        {sortEntries(props.rootEntries).map((entry) => (
          <FileTreeNode
            {...props}
            key={entry.path}
            entry={entry}
            depth={0}
            visibleNodes={visibleNodes}
            rowRefs={rowRefs}
          />
        ))}
        {props.rootEntries.length === 0 && !props.directories[""]?.loading && (
          <div className="agentspace-tree-message">工作空间为空</div>
        )}
        <TrashTree
          entries={props.trashEntries}
          expanded={props.trashExpanded}
          onToggle={props.onToggleTrash}
          onRestore={props.onRestoreTrash}
          onPurge={props.onPurgeTrash}
          onEmpty={props.onEmptyTrash}
        />
      </div>
    </div>
  );
}
