import { useEffect, useState } from "react";
import FileTree from "../components/agentspace/FileTree";
import EditorArea from "../components/agentspace/EditorArea";
import StatusBar from "../components/agentspace/StatusBar";
import AgentspaceDialogs from "../components/agentspace/AgentspaceDialogs";
import ConflictDialog from "../components/agentspace/ConflictDialog";
import { useAgentspace } from "../hooks/useAgentspace";
import { usePersistentState } from "../hooks/usePersistentState";
import { useResizable } from "../hooks/useResizable";
import { DIMENSIONS } from "../constants/dimensions";
import { STORAGE_KEYS } from "../constants/storage";
import type {
  AgentspaceDialogState,
  CursorPosition,
  DangerousDecision,
  DirtyCloseDecision,
  FileEntry,
  TrashDirtyDecision,
} from "../types";
import { isPathWithin } from "../utils/agentspacePath";
import "../styles/agentspace.css";

export default function Agentspace() {
  const agentspace = useAgentspace();
  const [dialog, setDialog] = useState<AgentspaceDialogState | null>(null);
  const [conflictTabId, setConflictTabId] = useState<string | null>(null);
  const [cursor, setCursor] = useState<CursorPosition | null>(null);
  const [sidebarWidth, setSidebarWidth] = usePersistentState<number>(
    STORAGE_KEYS.AGENTSPACE_SIDEBAR_WIDTH,
    DIMENSIONS.AGENTSPACE_SIDEBAR_DEFAULT,
  );
  const [sidebarCollapsed, setSidebarCollapsed] = usePersistentState(
    STORAGE_KEYS.AGENTSPACE_SIDEBAR_COLLAPSED,
    false,
  );
  const sidebarResize = useResizable({
    width: sidebarWidth,
    setWidth: setSidebarWidth,
    min: DIMENSIONS.AGENTSPACE_SIDEBAR_MIN,
    max: DIMENSIONS.AGENTSPACE_SIDEBAR_MAX,
    direction: "left",
  });

  const activeTab = agentspace.openTabs.find((tab) => tab.id === agentspace.activeTabId) || null;
  const conflictTab = agentspace.openTabs.find((tab) => tab.id === conflictTabId && tab.conflict) || null;
  const rootEntries = agentspace.directories[""]?.entries || [];

  useEffect(() => {
    void agentspace.loadDirectory("", true);
  }, []);

  useEffect(() => {
    if (!agentspace.hasDirtyTabs) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [agentspace.hasDirtyTabs]);

  const requestTrash = (entry: FileEntry) => {
    const dirtyIds = agentspace.openTabs
      .filter((tab) => isPathWithin(tab.path, entry.path) && tab.isDirty)
      .map((tab) => tab.id);
    if (dirtyIds.length) {
      setDialog({ kind: "trash-dirty", path: entry.path, tabIds: dirtyIds });
    } else {
      void agentspace.movePathToTrash(entry.path);
    }
  };

  const requestClose = (tabId: string) => {
    const tab = agentspace.openTabs.find((item) => item.id === tabId);
    if (!tab) return;
    if (tab.isDirty) setDialog({ kind: "close-dirty", tabId });
    else agentspace.closeCleanTab(tabId);
  };

  const submitName = async (value: string) => {
    if (!dialog) return;
    if (dialog.kind === "create-file") {
      await agentspace.createFile(dialog.parentPath, value);
    } else if (dialog.kind === "create-folder") {
      await agentspace.createFolder(dialog.parentPath, value);
    } else if (dialog.kind === "rename") {
      await agentspace.renamePath(dialog.entry.path, value);
    }
    setDialog(null);
  };

  const closeDirty = async (decision: DirtyCloseDecision) => {
    if (!dialog || dialog.kind !== "close-dirty") return;
    if (decision === "cancel") {
      setDialog(null);
      return;
    }
    if (decision === "save" && !await agentspace.saveFile(dialog.tabId)) return;
    agentspace.discardAndCloseTab(dialog.tabId);
    setDialog(null);
  };

  const trashDirty = async (decision: TrashDirtyDecision) => {
    if (!dialog || dialog.kind !== "trash-dirty") return;
    if (decision === "cancel") {
      setDialog(null);
      return;
    }
    if (decision === "save-all") {
      for (const tabId of dialog.tabIds) {
        if (!await agentspace.saveFile(tabId)) return;
      }
    }
    for (const tabId of dialog.tabIds) agentspace.discardAndCloseTab(tabId);
    const path = dialog.path;
    setDialog(null);
    await agentspace.movePathToTrash(path);
  };

  const dangerous = async (decision: DangerousDecision) => {
    if (!dialog || (dialog.kind !== "purge-trash" && dialog.kind !== "empty-trash")) return;
    if (decision === "confirm") {
      if (dialog.kind === "purge-trash") await agentspace.purgeTrashEntry(dialog.entryId);
      else await agentspace.emptyTrash();
    }
    setDialog(null);
  };

  const syncLabel = agentspace.syncState === "live"
    ? "已实时同步"
    : agentspace.syncState === "connecting"
      ? "正在连接"
      : "同步已降级";

  return (
    <div className="agentspace-layout">
      <div className="agentspace-topbar">
        <div className="agentspace-topbar-leading">
          <button
            className="agentspace-topbar-btn agentspace-sidebar-toggle"
            onClick={() => setSidebarCollapsed((value) => !value)}
            title={sidebarCollapsed ? "展开文件树" : "折叠文件树"}
          >
            {sidebarCollapsed ? "显示文件树" : "隐藏文件树"}
          </button>
          <span className="agentspace-topbar-title">Agentspace 编辑器</span>
        </div>
        <div className="agentspace-topbar-actions">
          <span className={`agentspace-sync-badge agentspace-sync-${agentspace.syncState}`}>{syncLabel}</span>
          <button className="agentspace-topbar-btn" onClick={() => void agentspace.refreshExpandedDirectories()} title="刷新已展开目录">
            刷新
          </button>
          <button
            className="agentspace-topbar-btn"
            disabled={!activeTab?.isDirty || activeTab.isLocked || !!activeTab.conflict}
            onClick={() => activeTab && void agentspace.saveFile(activeTab.id)}
            title="保存当前文件"
          >
            保存
          </button>
        </div>
      </div>

      <div className="agentspace-main">
        {!sidebarCollapsed && (
          <>
            <aside
              className="agentspace-sidebar"
              style={{ width: sidebarWidth }}
              aria-label="Agentspace 文件树"
            >
              <FileTree
                rootEntries={rootEntries}
                directories={agentspace.directories}
                expandedPaths={agentspace.expandedPaths}
                selection={agentspace.selection}
                activePath={activeTab?.path || null}
                locks={agentspace.locks}
                trashEntries={agentspace.trashEntries}
                trashExpanded={agentspace.trashExpanded}
                onSelect={agentspace.selectEntry}
                onToggleDirectory={agentspace.toggleDirectory}
                onOpenFile={agentspace.openFile}
                onRequestCreate={(kind, parentPath) => setDialog({ kind: kind === "file" ? "create-file" : "create-folder", parentPath })}
                onRequestRename={(entry) => setDialog({ kind: "rename", entry })}
                onRequestTrash={requestTrash}
                onToggleTrash={() => agentspace.setTrashExpanded(!agentspace.trashExpanded)}
                onRestoreTrash={agentspace.restoreTrashEntry}
                onPurgeTrash={(entryId) => {
                  const entry = agentspace.trashEntries.find((item) => item.entry_id === entryId);
                  setDialog({ kind: "purge-trash", entryId, displayName: entry?.name || entryId });
                }}
                onEmptyTrash={() => setDialog({ kind: "empty-trash", count: agentspace.trashEntries.length })}
              />
            </aside>
            <div
              className={`agentspace-sidebar-resize-handle ${sidebarResize.isResizing ? "dragging" : ""}`}
              role="separator"
              aria-label="调整文件树宽度"
              aria-orientation="vertical"
              tabIndex={0}
              onPointerDown={sidebarResize.onPointerDown}
              onKeyDown={(event) => {
                if (event.key === "ArrowLeft") setSidebarWidth((width) => Math.max(DIMENSIONS.AGENTSPACE_SIDEBAR_MIN, width - 10));
                if (event.key === "ArrowRight") setSidebarWidth((width) => Math.min(DIMENSIONS.AGENTSPACE_SIDEBAR_MAX, width + 10));
              }}
            />
          </>
        )}

        <main className="agentspace-content">
          <EditorArea
            tabs={agentspace.openTabs}
            activeTabId={agentspace.activeTabId}
            onTabClick={agentspace.setActiveTab}
            onRequestClose={requestClose}
            onContentChange={agentspace.updateContent}
            onSave={async (id) => { await agentspace.saveFile(id); }}
            onOpenConflict={setConflictTabId}
            onCursorChange={setCursor}
          />
          <StatusBar activeTab={activeTab} cursor={cursor} syncState={agentspace.syncState} />
        </main>
      </div>

      <AgentspaceDialogs
        dialog={dialog}
        onCancel={() => setDialog(null)}
        onSubmitName={submitName}
        onDirtyClose={closeDirty}
        onTrashDirty={trashDirty}
        onDangerous={dangerous}
      />

      {conflictTab && (
        <ConflictDialog
          tab={conflictTab}
          onUseDisk={(id) => { agentspace.resolveConflictWithDisk(id); setConflictTabId(null); }}
          onUseLocal={async (id) => {
            const saved = await agentspace.resolveConflictWithLocal(id);
            if (saved) setConflictTabId(null);
            return saved;
          }}
          onRecreate={async (id) => {
            const recreated = await agentspace.recreateDeletedConflict(id);
            if (recreated) setConflictTabId(null);
            return recreated;
          }}
          onDiscardDeleted={(id) => { agentspace.discardDeletedConflict(id); setConflictTabId(null); }}
          onCancel={() => setConflictTabId(null)}
        />
      )}

      {agentspace.error && (
        <div className="agentspace-error-toast" role="alert">
          <span>{agentspace.error.message}</span>
          {agentspace.error.retry && (
            <button onClick={() => void agentspace.error?.retry?.()}>重试</button>
          )}
          <button aria-label="关闭错误" onClick={agentspace.clearError}>×</button>
        </div>
      )}
    </div>
  );
}
