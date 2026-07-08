import { useState } from "react";
import type { FileEntry } from "../../types";

interface FileTreeProps {
  entries: FileEntry[];
  parentPath: string;
  depth: number;
  dirContents: Record<string, FileEntry[]>;
  activePath: string | null;
  disabled: boolean;
  onToggleDir: (path: string) => void;
  onOpenFile: (path: string) => void;
  onNewFile: (parentDir: string) => void;
  onNewFolder: (parentDir: string) => void;
  onDelete: (path: string) => void;
  onRename: (oldPath: string) => void;
}

function FileTreeNode({
  entry,
  parentPath,
  depth,
  dirContents,
  activePath,
  disabled,
  onToggleDir,
  onOpenFile,
  onDelete,
  onRename,
}: {
  entry: FileEntry;
  parentPath: string;
  depth: number;
  dirContents: Record<string, FileEntry[]>;
  activePath: string | null;
  disabled: boolean;
  onToggleDir: (path: string) => void;
  onOpenFile: (path: string) => void;
  onDelete: (path: string) => void;
  onRename: (path: string) => void;
}) {
  const isDir = entry.type === "dir";
  const fullPath = parentPath ? `${parentPath}/${entry.name}` : entry.name;
  const isExpanded = !!dirContents[fullPath];
  const isActive = activePath === fullPath;
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number } | null>(null);
  const children = isExpanded ? dirContents[fullPath] : null;

  const handleClick = () => {
    if (isDir) {
      onToggleDir(fullPath);
    } else {
      onOpenFile(fullPath);
    }
  };

  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY });
  };

  return (
    <div>
      <div
        className={`agentspace-file-item ${isActive ? "agentspace-file-item-active" : ""}`}
        style={{ paddingLeft: 16 + depth * 16 }}
        onClick={handleClick}
        onContextMenu={handleContextMenu}
      >
        <span className="agentspace-file-icon">
          {isDir ? (isExpanded ? "\u25BE" : "\u25B8") : "\u2022"}
        </span>
        <span className="agentspace-file-name">{entry.name}</span>
      </div>

      {/* 子目录展开 */}
      {isDir && isExpanded && children && children.length > 0 && (
        <FileTree
          entries={children}
          parentPath={fullPath}
          depth={depth + 1}
          dirContents={dirContents}
          activePath={activePath}
          disabled={disabled}
          onToggleDir={onToggleDir}
          onOpenFile={onOpenFile}
          onNewFile={() => {}}
          onNewFolder={() => {}}
          onDelete={onDelete}
          onRename={onRename}
        />
      )}

      {contextMenu && !disabled && (
        <div
          className="agentspace-context-menu"
          style={{ left: contextMenu.x, top: contextMenu.y, position: "fixed" }}
          onClick={() => setContextMenu(null)}
        >
          <div
            className="agentspace-context-menu-item"
            onClick={(e) => {
              e.stopPropagation();
              onDelete(fullPath);
              setContextMenu(null);
            }}
          >
            Delete
          </div>
          <div
            className="agentspace-context-menu-item"
            onClick={(e) => {
              e.stopPropagation();
              onRename(fullPath);
              setContextMenu(null);
            }}
          >
            Rename
          </div>
        </div>
      )}

      {contextMenu && (
        <div
          className="agentspace-context-menu-backdrop"
          onClick={() => setContextMenu(null)}
          style={{ position: "fixed", inset: 0, zIndex: 99 }}
        />
      )}
    </div>
  );
}

export default function FileTree({
  entries,
  parentPath,
  depth,
  dirContents,
  activePath,
  disabled,
  onToggleDir,
  onOpenFile,
  onNewFile,
  onNewFolder,
  onDelete,
  onRename,
}: FileTreeProps) {
  const isRoot = depth === 0;

  return (
    <div className="agentspace-file-tree">
      {isRoot && (
        <div className="agentspace-file-tree-toolbar">
          <button
            className="agentspace-toolbar-btn"
            title="New File"
            disabled={disabled}
            onClick={() => onNewFile(parentPath)}
          >
            + File
          </button>
          <button
            className="agentspace-toolbar-btn"
            title="New Folder"
            disabled={disabled}
            onClick={() => onNewFolder(parentPath)}
          >
            + Dir
          </button>
        </div>
      )}
      <div className="agentspace-file-tree-list">
        {entries.map((entry) => (
          <FileTreeNode
            key={parentPath ? `${parentPath}/${entry.name}` : entry.name}
            entry={entry}
            parentPath={parentPath}
            depth={depth}
            dirContents={dirContents}
            activePath={activePath}
            disabled={disabled}
            onToggleDir={onToggleDir}
            onOpenFile={onOpenFile}
            onDelete={onDelete}
            onRename={onRename}
          />
        ))}
      </div>
    </div>
  );
}