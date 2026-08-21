import { useEffect, useRef, useState } from "react";
import Sidebar from "./Sidebar";
import Header from "./Header";
import ChatArea from "./ChatArea";
import InputBar from "./InputBar";
import ClipboardPanel from "./ClipboardPanel";
import Drawer from "./Drawer";
import SubagentPanel from "./SubagentPanel";
import CronCountdown from "./CronCountdown";
import SubagentCountdown from "./SubagentCountdown";
import Lightbox from "./Lightbox";
import SecretBanner from "./SecretBanner";
import LlmProfileDrawer from "./LlmProfileDrawer";
import type { WebSocketState } from "../hooks/useWebSocket";
import { STORAGE_KEYS } from "../constants/storage";
import { DIMENSIONS } from "../constants/dimensions";
import { usePersistentState } from "../hooks/usePersistentState";
import { usePersistentSessionState } from "../hooks/usePersistentSessionState";
import { useResizable } from "../hooks/useResizable";

interface LayoutProps {
  ws: WebSocketState;
  onContextMenu: (e: React.MouseEvent, sid: string) => void;
  contextMenuOpen: boolean;
}

export default function Layout({ ws, onContextMenu, contextMenuOpen }: LayoutProps) {
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);
  const [llmDrawerOpen, setLlmDrawerOpen] = usePersistentState(STORAGE_KEYS.LLM_DRAWER_OPEN, false);
  const [sidebarCollapsed, setSidebarCollapsed] = usePersistentState(STORAGE_KEYS.SIDEBAR_COLLAPSED, false);
  const [drawerOpen, setDrawerOpen] = usePersistentState(STORAGE_KEYS.DRAWER_OPEN, false);
  const [subagentPanelOpen, setSubagentPanelOpen] = usePersistentSessionState<boolean>(
    STORAGE_KEYS.SUBAGENT_PANEL_OPEN, ws.sessionId, false);
  const [activeSubagentId, setActiveSubagentId] = usePersistentSessionState<string | null>(
    STORAGE_KEYS.ACTIVE_SUBAGENT_ID, ws.sessionId, null);
  const [targetSessions, setTargetSessions] = usePersistentSessionState<string[]>(
    STORAGE_KEYS.TARGET_SESSIONS, ws.sessionId, ["main"]);
  const [visibleCharacters, setVisibleCharacters] = usePersistentSessionState<string[]>(
    STORAGE_KEYS.VISIBLE_CHARACTERS, ws.sessionId, ["all-agents"]);
  const [responseCharacters, setResponseCharacters] = usePersistentSessionState<string[]>(
    STORAGE_KEYS.RESPONSE_CHARACTERS, ws.sessionId, ["main-agent"]);

  const [subagentPanelWidth, setSubagentPanelWidth] = usePersistentState<number>(
    STORAGE_KEYS.SUBAGENT_PANEL_WIDTH, DIMENSIONS.SUBAGENT_PANEL_DEFAULT);
  const subagentResize = useResizable({
    width: subagentPanelWidth,
    setWidth: setSubagentPanelWidth,
    min: DIMENSIONS.SUBAGENT_PANEL_MIN,
    max: DIMENSIONS.SUBAGENT_PANEL_MAX,
    direction: "right",
  });

  const [sidebarWidth, setSidebarWidth] = usePersistentState<number>(
    STORAGE_KEYS.SIDEBAR_WIDTH, DIMENSIONS.SIDEBAR_DEFAULT);
  const sidebarResize = useResizable({
    width: sidebarWidth,
    setWidth: setSidebarWidth,
    min: DIMENSIONS.SIDEBAR_MIN,
    max: DIMENSIONS.SIDEBAR_MAX,
    direction: "left",
  });

  const [drawerWidth, setDrawerWidth] = usePersistentState<number>(
    STORAGE_KEYS.DRAWER_WIDTH, DIMENSIONS.DRAWER_DEFAULT);
  const drawerResize = useResizable({
    width: drawerWidth,
    setWidth: setDrawerWidth,
    min: DIMENSIONS.DRAWER_MIN,
    max: DIMENSIONS.DRAWER_MAX,
    direction: "right",
  });

  const [llmDrawerWidth, setLlmDrawerWidth] = usePersistentState<number>(
    STORAGE_KEYS.LLM_DRAWER_WIDTH, DIMENSIONS.LLM_DRAWER_DEFAULT);
  const llmDrawerResize = useResizable({
    width: llmDrawerWidth,
    setWidth: setLlmDrawerWidth,
    min: DIMENSIONS.LLM_DRAWER_MIN,
    max: DIMENSIONS.LLM_DRAWER_MAX,
    direction: "right",
  });

  const prevSubagentIdsRef = useRef<Record<string, Set<string>>>({});
  const [isMobile, setIsMobile] = useState(false);
  const [taskProgressCollapsed, setTaskProgressCollapsed] = usePersistentState(STORAGE_KEYS.TASK_PROGRESS_COLLAPSED, false);
  const [clipboardCollapsed, setClipboardCollapsed] = usePersistentState(STORAGE_KEYS.CLIPBOARD_COLLAPSED, false);
  const [headerCollapsed, setHeaderCollapsed] = usePersistentState(STORAGE_KEYS.HEADER_COLLAPSED, false);

  // 移动端默认折叠侧边栏
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${DIMENSIONS.MOBILE_BREAKPOINT}px)`);
    setIsMobile(mq.matches);
    if (mq.matches) {
      setSidebarCollapsed(true);
      setTaskProgressCollapsed(true);
    }
    const onChange = (e: MediaQueryListEvent) => {
      setIsMobile(e.matches);
      if (e.matches) {
        setSidebarCollapsed(true);
        setTaskProgressCollapsed(true);
      }
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  // 子 Agent 停止或完成后，清理 targetSessions 中已失效的 session id
  useEffect(() => {
    const currentIds = new Set(Object.keys(ws.subagentSessions));
    const prevIds = prevSubagentIdsRef.current[ws.sessionId] || new Set();
    prevSubagentIdsRef.current[ws.sessionId] = currentIds;

    const hasRemoval = Array.from(prevIds).some((id) => !currentIds.has(id));
    if (!hasRemoval) return;

    setTargetSessions((prev) => {
      const activeIds = new Set(["main", ...Object.keys(ws.subagentSessions)]);
      const cleaned = prev.filter((id) => activeIds.has(id));
      if (cleaned.length === 0 || !cleaned.includes("main")) {
        return ["main"];
      }
      return cleaned;
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
    setVisibleCharacters(newVisible);
    setResponseCharacters(curResponse);
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

  const currentSessionArchived = ws.sessions.find((s) => s.id === ws.sessionId)?.status === "archived";
  // 空态判定与 ChatArea.isEmpty 一致：无 user/assistant 消息且无流式且无等待
  // （chatEmpty 时进度条不渲染，见 InputBar）
  const chatEmpty = !ws.messages.some((m) => m.role === "user" || m.role === "assistant")
    && !ws.streamingMessage && !ws.waiting;

  return (
    <>
      <Sidebar
        collapsed={sidebarCollapsed}
        isMobile={isMobile}
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
        onEnterColloquy={ws.enterColloquy}
        onSwitchSession={ws.switchSession}
        onContextMenu={onContextMenu}
        contextMenuOpen={contextMenuOpen}
        renamingSessionId={ws.renamingSessionId}
        setRenamingSessionId={ws.setRenamingSessionId}
        renameSession={ws.renameSession}
        onMergeSessions={(sources) => {
          ws.mergeSessions(sources);
          ws.setMergeMode(false);
          ws.setSelectedForMerge(new Set());
        }}
        sidebarItems={ws.sidebarItems}
        expandedClusters={ws.expandedClusters}
        toggleCluster={ws.toggleCluster}
        isReady={ws.isReady}
        width={sidebarWidth}
        isResizing={sidebarResize.isResizing}
        onResizePointerDown={sidebarResize.onPointerDown}
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
          yoloMode={ws.yoloMode}
          approvalModelAvailable={ws.approvalModelAvailable}
          approvalModelName={ws.approvalModelName}
          approvalModelType={ws.approvalModelType}
          llmModelName={ws.llmModelName}
          sidebarCollapsed={sidebarCollapsed}
          onToggleSidebar={() => setSidebarCollapsed((v) => !v)}
          onToggleHandsfree={ws.toggleHandsfree}
          agents={ws.agents}
          collapsed={headerCollapsed}
          onToggleCollapse={() => setHeaderCollapsed((v) => !v)}
          isMobile={isMobile}
          llmProfiles={ws.llmProfiles}
        />

        <ClipboardPanel
          clipboardDisplays={ws.clipboardDisplays}
          collapsed={clipboardCollapsed}
          onToggleCollapse={() => setClipboardCollapsed((v) => !v)}
        />

        <SecretBanner
          banner={ws.secretBanner}
          onDismiss={() => ws.setSecretBanner(null)}
        />

        <ChatArea
          messages={ws.messages}
          waiting={ws.waiting}
          archived={currentSessionArchived}
          sessionId={ws.sessionId}
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
          isReady={ws.isReady}
        >
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
            hasActiveProfile={!!ws.llmProfiles?.activeProfile}
            sessionId={ws.sessionId}
            chatEmpty={chatEmpty}
            taskProgress={ws.taskProgress}
            taskProgressCollapsed={taskProgressCollapsed}
            onToggleTaskProgressCollapse={() => setTaskProgressCollapsed((v) => !v)}
            onSend={() => {
              ws.send(targetSessions, visibleCharacters, responseCharacters);
            }}
            onUpload={ws.handleFileInputChange}
            onUploadClick={ws.handleUploadClick}
            onInterrupt={ws.interrupt}
            onDisgust={ws.disgust}
            fileInputRef={ws.fileInputRef}
            pendingImages={ws.pendingImages}
            onRemovePendingImage={ws.removePendingImage}
            onPasteImage={ws.handlePasteImages}
            pendingAudios={ws.pendingAudios}
            onRemovePendingAudio={ws.removePendingAudio}
            onPasteAudio={ws.handlePasteAudios}
            inputRef={ws.inputRef}
            subagentSessions={ws.subagentSessions}
            targetSessions={targetSessions}
            setTargetSessions={setTargetSessions}
            agents={ws.agents}
            visibleCharacters={visibleCharacters}
            responseCharacters={responseCharacters}
            onToggleAgentState={onToggleAgentState}
            pendingAsks={ws.pendingAsks}
            pendingConfirms={ws.pendingConfirms}
            onRespondAsk={ws.respondAsk}
            onRespondConfirm={ws.respondConfirm}
          />
        </ChatArea>

      </div>

      {!(drawerOpen || subagentPanelOpen || llmDrawerOpen) && (
        <div className="right-trigger-strip">
          <div
            className="right-trigger-bar resource-trigger-bar"
            onClick={() => setDrawerOpen(true)}
            data-tooltip="打开资源/任务抽屉"
          >
            <span className="right-trigger-icon">◀</span>
          </div>
          {Object.keys(ws.subagentSessions).length > 0 && (
            <div
              className="right-trigger-bar subagent-trigger-bar"
              onClick={() => setSubagentPanelOpen(true)}
              data-tooltip="展开子会话面板"
            >
              <span className="right-trigger-icon">◀</span>
            </div>
          )}
          <div
            className="right-trigger-bar llm-trigger-bar"
            onClick={() => setLlmDrawerOpen(true)}
            data-tooltip="打开模型配置抽屉"
          >
            <span className="right-trigger-icon">◀</span>
          </div>
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
        dynamicEndpoints={ws.dynamicEndpoints}
        width={drawerWidth}
        isResizing={drawerResize.isResizing}
        onResizePointerDown={drawerResize.onPointerDown}
      />

      {subagentPanelOpen && (
        <div
          className={`subagent-panel-resize-handle ${subagentResize.isResizing ? "dragging" : ""}`}
          onPointerDown={subagentResize.onPointerDown}
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

      {llmDrawerOpen && ws.llmProfiles && (
        <LlmProfileDrawer
          open={llmDrawerOpen}
          onClose={() => setLlmDrawerOpen(false)}
          llmProfiles={ws.llmProfiles}
          width={llmDrawerWidth}
          isResizing={llmDrawerResize.isResizing}
          onResizePointerDown={llmDrawerResize.onPointerDown}
        />
      )}
    </>
  );
}