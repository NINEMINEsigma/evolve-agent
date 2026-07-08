import { useEffect, useState } from "react";
import FileTree from "../components/agentspace/FileTree";
import EditorArea from "../components/agentspace/EditorArea";
import StatusBar from "../components/agentspace/StatusBar";
import { useAgentspace } from "../hooks/useAgentspace";
import "../styles/agentspace.css";

export default function Agentspace() {
  const as = useAgentspace();
  const activeTab = as.openTabs.find((t) => t.id === as.activeTabId);

  // 新建文件弹窗
  const [newFileDialog, setNewFileDialog] = useState(false);
  const [newFileName, setNewFileName] = useState("");
  const [newFolderDialog, setNewFolderDialog] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");

  // 初始加载根目录
  useEffect(() => {
    as.loadDirectory("");
  }, []);

  // 轮询锁状态
  useEffect(() => {
    as.loadLockStatus();
    const interval = setInterval(() => as.loadLockStatus(), 3000);
    return () => clearInterval(interval);
  }, [as.loadLockStatus]);

  const handleNewFile = (_parentDir: string) => {
    setNewFileDialog(true);
  };

  const handleNewFolder = (_parentDir: string) => {
    setNewFolderDialog(true);
  };

  const confirmNewFile = async () => {
    if (!newFileName.trim()) return;
    await as.createFile(as.currentDir, newFileName.trim());
    setNewFileName("");
    setNewFileDialog(false);
  };

  const confirmNewFolder = async () => {
    if (!newFolderName.trim()) return;
    await as.createFolder(as.currentDir, newFolderName.trim());
    setNewFolderName("");
    setNewFolderDialog(false);
  };

  return (
    <div className="agentspace-layout">
      {/* Top Bar */}
      <div className="agentspace-topbar">
        <span className="agentspace-topbar-title">Agentspace Explorer</span>
        <div className="agentspace-topbar-actions">
          <button
            className="agentspace-topbar-btn"
            onClick={() => as.refresh()}
            title="Refresh"
          >
            Refresh
          </button>
          {as.locked && (
            <span className="agentspace-lock-indicator">Read-only (Agent working)</span>
          )}
        </div>
      </div>

      {/* Main */}
      <div className="agentspace-main">
        <div className="agentspace-sidebar">
          <FileTree
            entries={as.dirContents[""] || []}
            parentPath=""
            depth={0}
            dirContents={as.dirContents}
            activePath={activeTab?.path || null}
            disabled={as.locked}
            onToggleDir={as.toggleDir}
            onOpenFile={as.openFile}
            onNewFile={handleNewFile}
            onNewFolder={handleNewFolder}
            onDelete={as.deletePath}
            onRename={(oldPath) => {
              const newName = prompt("New name:", oldPath);
              if (newName && newName !== oldPath) {
                as.renamePath(oldPath, newName);
              }
            }}
          />
        </div>

        <div className="agentspace-content">
          <EditorArea
            tabs={as.openTabs}
            activeTabId={as.activeTabId}
            locked={as.locked}
            onTabClick={as.setActiveTab}
            onTabClose={as.closeTab}
            onContentChange={as.updateContent}
            onSave={as.saveFile}
          />
          <StatusBar
            activeFilePath={activeTab?.path || null}
            language={activeTab?.language || null}
            locked={as.locked}
          />
        </div>
      </div>

      {/* New File Dialog */}
      {newFileDialog && (
        <div className="agentspace-dialog-overlay" onClick={() => setNewFileDialog(false)}>
          <div className="agentspace-dialog" onClick={(e) => e.stopPropagation()}>
            <h3>New File</h3>
            <input
              className="agentspace-dialog-input"
              value={newFileName}
              onChange={(e) => setNewFileName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") confirmNewFile(); if (e.key === "Escape") setNewFileDialog(false); }}
              placeholder="filename.ext"
              autoFocus
            />
            <div className="agentspace-dialog-actions">
              <button onClick={() => setNewFileDialog(false)}>Cancel</button>
              <button onClick={confirmNewFile}>Create</button>
            </div>
          </div>
        </div>
      )}

      {/* New Folder Dialog */}
      {newFolderDialog && (
        <div className="agentspace-dialog-overlay" onClick={() => setNewFolderDialog(false)}>
          <div className="agentspace-dialog" onClick={(e) => e.stopPropagation()}>
            <h3>New Folder</h3>
            <input
              className="agentspace-dialog-input"
              value={newFolderName}
              onChange={(e) => setNewFolderName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") confirmNewFolder(); if (e.key === "Escape") setNewFolderDialog(false); }}
              placeholder="folder-name"
              autoFocus
            />
            <div className="agentspace-dialog-actions">
              <button onClick={() => setNewFolderDialog(false)}>Cancel</button>
              <button onClick={confirmNewFolder}>Create</button>
            </div>
          </div>
        </div>
      )}

      {/* Error toast */}
      {as.error && (
        <div className="agentspace-error-toast" onClick={() => as.refresh()}>
          {as.error}
          <span className="agentspace-error-close">&times;</span>
        </div>
      )}
    </div>
  );
}