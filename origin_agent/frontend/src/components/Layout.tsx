import { useCallback, useEffect, useRef, useState } from "react";
import Sidebar from "./Sidebar";
import Header from "./Header";
import ChatArea from "./ChatArea";
import InputBar from "./InputBar";
import TaskProgressPanel from "./TaskProgressPanel";
import UnifiedPanel from "./UnifiedPanel";
import Drawer from "./Drawer";
import SubagentPanel from "./SubagentPanel";
import CronCountdown from "./CronCountdown";
import SubagentCountdown from "./SubagentCountdown";
import Lightbox from "./Lightbox";
import ConfirmDialog from "./ConfirmDialog";
import AskDialog from "./AskDialog";
import type { WebSocketState } from "../hooks/useWebSocket";

interface LayoutProps {
  ws: WebSocketState;
  onContextMenu: (e: React.MouseEvent, sid: string) => void;
}

export default function Layout({ ws, onContextMenu }: LayoutProps) {
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [subagentPanelOpenMap, setSubagentPanelOpenMap] = useState<Record<string, boolean>>({});
  const [activeSubagentIdMap, setActiveSubagentIdMap] = useState<Record<string, string | null>>({});
  const [targetSessionsMap, setTargetSessionsMap] = useState<Record<string, string[]>>({});
  const [visibleCharactersMap, setVisibleCharactersMap] = useState<Record<string, string[]>>({});
  const [responseCharactersMap, setResponseCharactersMap] = useState<Record<string, string[]>>({});

  const subagentPanelOpen = subagentPanelOpenMap[ws.sessionId] || false;
  const activeSubagentId = activeSubagentIdMap[ws.sessionId] || null;
  const targetSessions = targetSessionsMap[ws.sessionId] || ["main"];
  const visibleCharacters = visibleCharactersMap[ws.sessionId] || ["all-agents"];
  const responseCharacters = responseCharactersMap[ws.sessionId] || ["main-agent"];

  const [subagentPanelWidth, setSubagentPanelWidth] = useState(() => {
    const saved = localStorage.getItem("evolve_subagent_panel_width");
    const parsed = saved ? parseInt(saved, 10) : 420;
    return isNaN(parsed) ? 420 : parsed;
  });
  const [resizingPanel, setResizingPanel] = useState(false);
  const subagentPanelWidthRef = useRef(subagentPanelWidth);
  useEffect(() => {
    subagentPanelWidthRef.current = subagentPanelWidth;
  }, [subagentPanelWidth]);

  const prevSubagentIdsRef = useRef<Record<string, Set<string>>>({});
  const [isMobile, setIsMobile] = useState(false);
  const [taskProgressCollapsed, setTaskProgressCollapsed] = useState(false);
  const [clipboardCollapsed, setClipboardCollapsed] = useState(false);
  const [headerCollapsed, setHeaderCollapsed] = useState(false);

  const setSubagentPanelOpen = (value: boolean | ((prev: boolean) => boolean)) => {
    setSubagentPanelOpenMap((prev) => ({
      ...prev,
      [ws.sessionId]: typeof value === "function" ? value(prev[ws.sessionId] || false) : value,
    }));
  };
  const setActiveSubagentId = (value: string | null | ((prev: string | null) => string | null)) => {
    setActiveSubagentIdMap((prev) => ({
      ...prev,
      [ws.sessionId]: typeof value === "function" ? value(prev[ws.sessionId] || null) : value,
    }));
  };
  const setTargetSessions = (value: string[] | ((prev: string[]) => string[])) => {
    setTargetSessionsMap((prev) => ({
      ...prev,
      [ws.sessionId]: typeof value === "function" ? value(prev[ws.sessionId] || ["main"]) : value,
    }));
  };

  // 移动端默认折叠侧边栏
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 768px)");
    const onChange = (e: MediaQueryListEvent) => {
      setIsMobile(e.matches);
      setSidebarCollapsed(e.matches);
      setTaskProgressCollapsed(e.matches);
    };
    setIsMobile(mq.matches);
    setSidebarCollapsed(mq.matches);
    setTaskProgressCollapsed(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  // 切换主会话时重置目标选择为默认值
  useEffect(() => {
    setTargetSessionsMap((prev) => {
      if (prev[ws.sessionId]) return prev;
      return { ...prev, [ws.sessionId]: ["main"] };
    });
  }, [ws.sessionId]);

  // 子 Agent 停止或完成后，清理 targetSessionsMap 中已失效的 session id
  useEffect(() => {
    const currentIds = new Set(Object.keys(ws.subagentSessions));
    const prevIds = prevSubagentIdsRef.current[ws.sessionId] || new Set();
    prevSubagentIdsRef.current[ws.sessionId] = currentIds;

    const hasRemoval = Array.from(prevIds).some((id) => !currentIds.has(id));
    if (!hasRemoval) return;

    setTargetSessionsMap((prev) => {
      const current = prev[ws.sessionId] || ["main"];
      const activeIds = new Set(["main", ...Object.keys(ws.subagentSessions)]);
      const cleaned = current.filter((id) => activeIds.has(id));
      if (cleaned.length === 0 || !cleaned.includes("main")) {
        return { ...prev, [ws.sessionId]: ["main"] };
      }
      return { ...prev, [ws.sessionId]: cleaned };
    });
  }, [ws.sessionId, ws.subagentSessions]);

  // 挂载时注册滚动监听
  useEffect(() => {
    const cleanup = ws.attachScrollListener();
    return cleanup;
  }, [ws.attachScrollListener]);

  const onToggleAgentState = (agentName: string) => {
    let curVisible = visibleCharacters.includes("all-agents")
      ? ws.agents
      : [...visibleCharacters];
    let curResponse = [...responseCharacters];
    const vis = curVisible.includes(agentName);
    const res = curResponse.includes(agentName);

    if (!vis && !res) {
      curVisible.push(agentName);
      curResponse = curResponse.filter((a) => a !== agentName);
    } else if (vis && !res) {
      if (!curResponse.includes(agentName)) curResponse.push(agentName);
    } else {
      curVisible = curVisible.filter((a) => a !== agentName);
      curResponse = curResponse.filter((a) => a !== agentName);
    }
    const allVisible = ws.agents.length > 0 && ws.agents.every((a) => curVisible.includes(a));
    const newVisible = allVisible ? ["all-agents"] : curVisible;
    setVisibleCharactersMap((prev) => ({ ...prev, [ws.sessionId]: newVisible }));
    setResponseCharactersMap((prev) => ({ ...prev, [ws.sessionId]: curResponse }));
  };

  const onToggleMessageVisibility = (messageId: string, agentName: string) => {
    const msg = ws.messages.find((m) => m.id === messageId);
    if (msg == null || typeof msg.messageIndex !== "number") return;
    let curVisible = [...(msg.visibleCharacters || ["all-agents"])];
    let curResponse = [...(msg.responseCharacters || [])];
    if (curVisible.includes("all-agents")) {
      curVisible = (ws.agents.length > 0 ? ws.agents : curVisible.filter((a) => a !== "all-agents"));
    }
    const vis = curVisible.includes(agentName);
    const res = curResponse.includes(agentName);
    if (!vis && !res) {
      curVisible.push(agentName);
      curResponse = curResponse.filter((a) => a !== agentName);
    } else if (vis && !res) {
      if (!curResponse.includes(agentName)) curResponse.push(agentName);
    } else {
      curVisible = curVisible.filter((a) => a !== agentName);
      curResponse = curResponse.filter((a) => a !== agentName);
    }
    const allVisible = ws.agents.length > 0 && ws.agents.every((a) => curVisible.includes(a));
    const newVisible = allVisible ? ["all-agents"] : curVisible;
    ws.updateMessageVisibility(msg.messageIndex, newVisible);
    ws.setMessages((prev) => prev.map((m) =>
      m.id === messageId ? { ...m, visibleCharacters: newVisible, responseCharacters: curResponse } : m
    ));
  };

  const handleResizePointerDown = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    setResizingPanel(true);
    const startX = e.clientX;
    const startWidth = subagentPanelWidthRef.current;

    const handleMove = (ev: PointerEvent) => {
      const delta = startX - ev.clientX;
      const newWidth = Math.max(280, Math.min(800, startWidth + delta));
      setSubagentPanelWidth(newWidth);
    };

    const handleUp = () => {
      setResizingPanel(false);
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
      localStorage.setItem("evolve_subagent_panel_width", String(subagentPanelWidthRef.current));
    };

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
  }, []);

  const currentSessionArchived = ws.sessions.find((s) => s.id === ws.sessionId)?.status === "archived";

  return (
    <>
      <Sidebar
        collapsed={sidebarCollapsed}
        sessions={ws.sessions}
        sessionId={ws.sessionId}
        searchQuery={ws.searchQuery}
        setSearchQuery={ws.setSearchQuery}
        allTags={ws.allTags}
        mergeMode={ws.mergeMode}
        selectedForMerge={ws.selectedForMerge}
        onToggleMergeMode={() => {
          ws.setMergeMode(!ws.mergeMode);
          ws.setSelectedForMerge(new Set());
        }}
        onToggleMergeSelect={ws.toggleMergeSelect}
        onNewChat={ws.newChat}
        onSwitchSession={ws.switchSession}
        onContextMenu={onContextMenu}
        onMergeSessions={(sources) => {
          ws.mergeSessions(sources);
          ws.setMergeMode(false);
          ws.setSelectedForMerge(new Set());
        }}
        sidebarItems={ws.sidebarItems}
        expandedClusters={ws.expandedClusters}
        toggleCluster={ws.toggleCluster}
      />

      {isMobile && !sidebarCollapsed && (
        <div className="sidebar-backdrop" onClick={() => setSidebarCollapsed(true)} />
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
          llmModelName={ws.llmModelName}
          sidebarCollapsed={sidebarCollapsed}
          onToggleSidebar={() => setSidebarCollapsed((v) => !v)}
          onToggleHandsfree={ws.toggleHandsfree}
          agents={ws.agents}
          collapsed={headerCollapsed}
          onToggleCollapse={() => setHeaderCollapsed((v) => !v)}
          isMobile={isMobile}
        />

        <TaskProgressPanel
          taskProgress={ws.taskProgress}
          collapsed={taskProgressCollapsed}
          onToggleCollapse={() => setTaskProgressCollapsed((v) => !v)}
        />

        <UnifiedPanel
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
          onDeleteMessages={ws.deleteMessages}
          onRegenerateResponse={ws.regenerateResponse}
          bottomRef={ws.bottomRef}
          chatAreaRef={ws.chatAreaRef}
          contentRef={ws.contentRef}
          onDropFiles={ws.handleFileUpload}
          streamingMessage={ws.streamingMessage}
          agents={ws.agents}
          onToggleMessageVisibility={onToggleMessageVisibility}
          onScrollToBottom={() => ws.scrollToBottomIfAtBottom(true)}
        />

        <CronCountdown cronTasks={ws.cronTasks} />

        <SubagentCountdown
          subagentSessions={ws.subagentSessions}
          idleCountdown={ws.subagentIdleCountdown}
        />

        <InputBar
          input={ws.input}
          setInput={ws.setInput}
          waiting={ws.waiting}
          uploading={ws.uploading}
          archived={currentSessionArchived}
          onSend={() => {
            ws.send(targetSessions, visibleCharacters, responseCharacters);
          }}
          onUpload={ws.handleFileInputChange}
          onUploadClick={ws.handleUploadClick}
          onInterrupt={ws.interrupt}
          fileInputRef={ws.fileInputRef}
          pendingImages={ws.pendingImages}
          onRemovePendingImage={ws.removePendingImage}
          onPasteImage={ws.handlePasteImages}
          inputRef={ws.inputRef}
          subagentSessions={ws.subagentSessions}
          targetSessions={targetSessions}
          setTargetSessions={setTargetSessions}
          agents={ws.agents}
          visibleCharacters={visibleCharacters}
          responseCharacters={responseCharacters}
          onToggleAgentState={onToggleAgentState}
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

      {!(drawerOpen || subagentPanelOpen) && (
        <div className="right-trigger-strip">
          <div
            className="right-trigger-bar resource-trigger-bar"
            onClick={() => setDrawerOpen(true)}
            data-tooltip="打开资源/任务抽屉"
          >
            <span className="right-trigger-icon">◀</span>
          </div>
          {Object.keys(ws.subagentSessions).length > 0 && !subagentPanelOpen && (
            <div
              className="right-trigger-bar subagent-trigger-bar"
              onClick={() => setSubagentPanelOpen(true)}
              data-tooltip="展开子会话面板"
            >
              <span className="right-trigger-icon">◀</span>
            </div>
          )}
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

      {subagentPanelOpen && (
        <div
          className={`subagent-panel-resize-handle ${resizingPanel ? "dragging" : ""}`}
          onPointerDown={handleResizePointerDown}
          data-tooltip="拖拽调整子会话面板宽度"
        />
      )}

      <SubagentPanel
        open={subagentPanelOpen}
        onToggle={() => setSubagentPanelOpen((v) => !v)}
        subagentSessions={ws.subagentSessions}
        activeId={activeSubagentId}
        onSelect={setActiveSubagentId}
        width={subagentPanelWidth}
      />

      {lightboxSrc && (
        <Lightbox src={lightboxSrc} onClose={() => setLightboxSrc(null)} />
      )}
    </>
  );
}