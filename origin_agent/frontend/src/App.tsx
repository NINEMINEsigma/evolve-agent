import { useEffect, useRef, useState } from "react";
import { useWebSocket } from "./hooks/useWebSocket";
import Sidebar from "./components/Sidebar";
import Header from "./components/Header";
import ChatArea from "./components/ChatArea";
import InputBar from "./components/InputBar";
import ConfirmDialog from "./components/ConfirmDialog";
import AskDialog from "./components/AskDialog";
import TaskProgressPanel from "./components/TaskProgressPanel";
import ClipboardPanel from "./components/ClipboardPanel";
import Drawer from "./components/Drawer";
import CronCountdown from "./components/CronCountdown";
import Lightbox from "./components/Lightbox";

export default function App() {
  const ws = useWebSocket();
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [taskProgressCollapsed, setTaskProgressCollapsed] = useState(false);
  const [clipboardCollapsed, setClipboardCollapsed] = useState(false);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; sid: string } | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // ── close context menu on outside click ──
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setContextMenu(null);
      }
    };
    const escHandler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setContextMenu(null);
    };
    if (contextMenu) {
      document.addEventListener("mousedown", handler);
      document.addEventListener("keydown", escHandler);
    }
    return () => {
      document.removeEventListener("mousedown", handler);
      document.removeEventListener("keydown", escHandler);
    };
  }, [contextMenu]);

  const handleContextMenu = (e: React.MouseEvent, sid: string) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({ x: e.clientX, y: e.clientY, sid });
  };

  const currentSessionArchived = ws.sessions.find((s) => s.id === ws.sessionId)?.status === "archived";

  return (
    <div className="app">
      <Sidebar
        collapsed={sidebarCollapsed}
        sessions={ws.sessions}
        sessionId={ws.sessionId}
        searchQuery={ws.searchQuery}
        setSearchQuery={ws.setSearchQuery}
        mergeMode={ws.mergeMode}
        selectedForMerge={ws.selectedForMerge}
        onToggleMergeMode={() => {
          ws.setMergeMode(!ws.mergeMode);
          ws.setSelectedForMerge(new Set());
        }}
        onToggleMergeSelect={ws.toggleMergeSelect}
        onNewChat={ws.newChat}
        onSwitchSession={ws.switchSession}
        onContextMenu={handleContextMenu}
        onMergeSessions={(sources) => {
          ws.mergeSessions(sources);
          ws.setMergeMode(false);
          ws.setSelectedForMerge(new Set());
        }}
        sidebarSessions={ws.sidebarSessions}
      />

      {contextMenu && (
        <div
          ref={menuRef}
          className="context-menu"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <div className="context-menu-item" onClick={() => { setContextMenu(null); ws.autoTitleSession(contextMenu.sid); }}>
            自动命名
          </div>
          <div className="context-menu-item" onClick={() => { setContextMenu(null); ws.togglePinSession(contextMenu.sid); }}>
            {(() => {
              const s = ws.sessions.find((s) => s.id === contextMenu.sid);
              return s?.pinned ? "取消收藏" : "收藏";
            })()}
          </div>
          {(() => {
            const s = ws.sessions.find((s) => s.id === contextMenu.sid);
            if (!s) return null;
            if (s.status === "archived") {
              return (
                <div className="context-menu-item" onClick={() => { setContextMenu(null); ws.branchSession(contextMenu.sid); }}>
                  继续此会话
                </div>
              );
            }
            const isTerminating = ws.terminatingSessions.has(contextMenu.sid);
            return (
              <div
                className={`context-menu-item ${isTerminating ? "context-menu-item-disabled" : ""}`}
                onClick={() => {
                  if (isTerminating) return;
                  setContextMenu(null);
                  ws.terminateSession(contextMenu.sid);
                }}
              >
                {isTerminating ? "⏳ 终结中..." : "终结"}
              </div>
            );
          })()}
          <div className="context-menu-separator" />
          <div className="context-menu-item context-menu-item-danger" onClick={() => { setContextMenu(null); ws.deleteSession(contextMenu.sid); }}>
            删除会话
          </div>
        </div>
      )}

      <div className="main-content">
        <Header
          status={ws.status}
          sessionId={ws.sessionId}
          tokenUsage={ws.tokenUsage}
          contextTokens={ws.contextTokens}
          llmMaxContextTokens={ws.llmMaxContextTokens}
          handsfreeMode={ws.handsfreeMode}
          approvalModelAvailable={ws.approvalModelAvailable}
          approvalModelName={ws.approvalModelName}
          sidebarCollapsed={sidebarCollapsed}
          onToggleSidebar={() => setSidebarCollapsed((v) => !v)}
          onToggleHandsfree={ws.toggleHandsfree}
        />

        <TaskProgressPanel
          taskProgress={ws.taskProgress}
          collapsed={taskProgressCollapsed}
          onToggleCollapse={() => setTaskProgressCollapsed((v) => !v)}
        />

        <ClipboardPanel
          clipboardDisplays={ws.clipboardDisplays}
          collapsed={clipboardCollapsed}
          onToggleCollapse={() => setClipboardCollapsed((v) => !v)}
        />

        <ChatArea
          messages={ws.messages}
          waiting={ws.waiting}
          archived={currentSessionArchived}
          onImageClick={setLightboxSrc}
          onToggleCollapse={ws.toggleMessageCollapse}
          onEditMessage={ws.editMessage}
          bottomRef={ws.bottomRef}
          onDropFiles={ws.handleFileUpload}
        />

        <CronCountdown cronTasks={ws.cronTasks} />

        <InputBar
          input={ws.input}
          setInput={ws.setInput}
          waiting={ws.waiting}
          uploading={ws.uploading}
          archived={currentSessionArchived}
          onSend={ws.send}
          onUpload={ws.handleFileInputChange}
          onUploadClick={ws.handleUploadClick}
          onInterrupt={ws.interrupt}
          fileInputRef={ws.fileInputRef}
          pendingImages={ws.pendingImages}
          onRemovePendingImage={ws.removePendingImage}
          onPasteImage={ws.handlePasteImages}
          inputRef={ws.inputRef}
        />

        <ConfirmDialog
          pendingConfirm={ws.pendingConfirm}
          denyReason={ws.denyReason}
          setDenyReason={ws.setDenyReason}
          onRespond={ws.respondConfirm}
        />

        <AskDialog
          pendingAsk={ws.pendingAsk}
          askCustomText={ws.askCustomText}
          setAskCustomText={ws.setAskCustomText}
          askSelectedOption={ws.askSelectedOption}
          setAskSelectedOption={ws.setAskSelectedOption}
          onRespond={ws.respondAsk}
        />
      </div>

      {!drawerOpen && (
        <div className="drawer-trigger-bar" onClick={() => setDrawerOpen(true)} title="打开资源/任务抽屉">
          <span className="drawer-trigger-icon">◀</span>
        </div>
      )}

      <Drawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        sessionId={ws.sessionId}
        messages={ws.messages}
        onImageClick={setLightboxSrc}
        bgTasks={ws.bgTasks}
        setBgTasks={ws.setBgTasks}
        cronTasks={ws.cronTasks}
        setCronTasks={ws.setCronTasks}
      />

      {lightboxSrc && (
        <Lightbox src={lightboxSrc} onClose={() => setLightboxSrc(null)} />
      )}
    </div>
  );
}