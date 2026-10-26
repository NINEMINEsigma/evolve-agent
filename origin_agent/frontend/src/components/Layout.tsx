import { useCallback, useEffect, useRef, useState } from "react";
import Sidebar from "./Sidebar";
import Header from "./Header";
import Lightbox from "./Lightbox";
import SessionLockOverlay from "./SessionLockOverlay";
import OnboardingTour from "./OnboardingTour";
import PerformanceTelemetryDialog from "./PerformanceTelemetryDialog";
import NoticeBanner from "./primitives/NoticeBanner";
import CommandMenu from "./CommandMenu";
import SessionExportDialog from "../features/sessionExport/SessionExportDialog";
import { useSessionExport } from "../features/sessionExport/useSessionExport";
import type { WebSocketState } from "../hooks/useWebSocket";
import { STORAGE_KEYS } from "../constants/storage";
import { COLLOQUY_SID } from "../constants/session";
import { DIMENSIONS } from "../constants/dimensions";
import { usePersistentState } from "../hooks/usePersistentState";
import { usePersistentSessionState } from "../hooks/usePersistentSessionState";
import { useResizable } from "../hooks/useResizable";
import { useSessionStage } from "../hooks/useSessionStage";
import { useSessionChatStyle } from "../hooks/useSessionChatStyle";
import { useChatRuntimeStore } from "../features/chat/chatRuntimeStore";
import { TAB_REGISTRY } from "../features/tabs/registry";
import { useTabSystem } from "../features/tabs/useTabSystem";
import TabRail from "../features/tabs/TabRail";
import TabRailFooter from "../features/tabs/TabRailFooter";
import TabStage from "../features/tabs/TabStage";
import { TabDataProvider } from "../features/tabs/TabDataContext";
import type { TabRenderContext } from "../features/tabs/registry";

interface LayoutProps {
  ws: WebSocketState;
  onContextMenu: (e: React.MouseEvent, sid: string) => void;
  contextMenuOpen: boolean;
  onboardingRun: boolean;
  onOnboardingClose: () => void;
}

export default function Layout({ ws, onContextMenu, contextMenuOpen, onboardingRun, onOnboardingClose }: LayoutProps) {
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);
  const [pinSidebar, setPinSidebar] = useState(false);
  const [commandMenuOpen, setCommandMenuOpen] = useState(false);
  const [performanceTelemetryOpen, setPerformanceTelemetryOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = usePersistentState(STORAGE_KEYS.SIDEBAR_COLLAPSED, false);
  const [targetSessions, setTargetSessions] = usePersistentSessionState<string[]>(
    STORAGE_KEYS.TARGET_SESSIONS, ws.sessionId, ["main"]);
  const [visibleCharacters, setVisibleCharacters] = usePersistentSessionState<string[]>(
    STORAGE_KEYS.VISIBLE_CHARACTERS, ws.sessionId, ["all-agents"]);
  const [responseCharacters, setResponseCharacters] = usePersistentSessionState<string[]>(
    STORAGE_KEYS.RESPONSE_CHARACTERS, ws.sessionId, []);

  const [stagePaused, setStagePaused] = usePersistentSessionState<boolean>(
    STORAGE_KEYS.STAGE_PAUSED, ws.sessionId, false);
  const [chatStylePaused, setChatStylePaused] = usePersistentSessionState<boolean>(
    STORAGE_KEYS.CHAT_STYLE_PAUSED, ws.sessionId, false);

  const exportProcessing = useChatRuntimeStore((state) => state.processing);
  const [exportNotice, setExportNotice] = useState<string | null>(null);
  useEffect(() => setExportNotice(null), [ws.sessionId]);
  const exportDisabled = !ws.sessionId || !ws.isReady || ws.sessionLocked;
  const sessionExport = useSessionExport({
    sessionId: ws.sessionId, processing: exportProcessing, disabled: exportDisabled,
    stagePaused, chatStylePaused, onNotice: setExportNotice,
  });
  const stageState = useSessionStage(ws.sessionId, stagePaused);
  const chatStyleState = useSessionChatStyle(ws.sessionId, chatStylePaused);
  const stageStatusText = stagePaused ? "已暂停" : stageState.status === "ready" ? "已启用" : stageState.status === "idle" ? "未配置" : "未配置";
  const chatStyleStatusText = chatStylePaused ? "已暂停" : chatStyleState.status === "ready" ? "已启用" : chatStyleState.status === "error" ? "加载失败" : "未配置";

  const [activeSubagentId, setActiveSubagentId] = usePersistentSessionState<string | null>(
    STORAGE_KEYS.ACTIVE_SUBAGENT_ID, ws.sessionId, null);
  const [sidebarWidth, setSidebarWidth] = usePersistentState<number>(
    STORAGE_KEYS.SIDEBAR_WIDTH, DIMENSIONS.SIDEBAR_DEFAULT);
  const sidebarResize = useResizable({
    width: sidebarWidth,
    setWidth: setSidebarWidth,
    min: DIMENSIONS.SIDEBAR_MIN,
    max: DIMENSIONS.SIDEBAR_MAX,
    direction: "left",
  });

  const prevSubagentIdsRef = useRef<Record<string, Set<string>>>({});
  const [isMobile, setIsMobile] = useState(false);
  const [clipboardCollapsed, setClipboardCollapsed] = usePersistentState(STORAGE_KEYS.CLIPBOARD_COLLAPSED, false);

  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${DIMENSIONS.MOBILE_BREAKPOINT}px)`);
    setIsMobile(mq.matches);
    if (mq.matches) setSidebarCollapsed(true);
    const onChange = (e: MediaQueryListEvent) => {
      setIsMobile(e.matches);
      if (e.matches) setSidebarCollapsed(true);
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    const currentIds = new Set(Object.keys(ws.subagentSessions));
    const prevIds = prevSubagentIdsRef.current[ws.sessionId] || new Set();
    prevSubagentIdsRef.current[ws.sessionId] = currentIds;

    const hasRemoval = Array.from(prevIds).some((id) => !currentIds.has(id));
    if (!hasRemoval) return;

    setTargetSessions((prev) => {
      const activeIds = new Set(["main", ...Object.keys(ws.subagentSessions)]);
      const cleaned = prev.filter((id) => activeIds.has(id));
      if (cleaned.length === 0 || !cleaned.includes("main")) return ["main"];
      return cleaned;
    });
  }, [ws.sessionId, ws.subagentSessions]);

  const onToggleAgentState = (agentName: string) => {
    let curVisible = visibleCharacters.includes("all-agents") ? ws.agents : [...visibleCharacters];
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

  const handleToggleMessageVisibility = useCallback((messageId: string, agentName: string) => {
    const msg = useChatRuntimeStore.getState().contentByRowId[messageId];
    if (msg == null || typeof msg.messageIndex !== "number") return;
    let curVisible = [...(msg.visibleCharacters || ["all-agents"])] as string[];
    let curResponse = [...(msg.responseCharacters || [])];
    if (curVisible.includes("all-agents")) {
      curVisible = ws.agents.length > 0 ? [...ws.agents] : curVisible.filter((a) => a !== "all-agents");
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
    ws.updateMessageVisibility(messageId, newVisible);
    useChatRuntimeStore.setState((state) => ({
      contentByRowId: {
        ...state.contentByRowId,
        [messageId]: { ...msg, visibleCharacters: newVisible, responseCharacters: curResponse },
      },
    }));
  }, [ws.agents, ws.updateMessageVisibility]);

  const currentSession = ws.sessions.find((session) => session.id === ws.sessionId);
  const currentSessionArchived = currentSession?.status === "archived";
  const sessionTitle = ws.sessionId === COLLOQUY_SID
    ? "随意聊聊"
    : currentSession?.title || "未命名会话";

  const tabSystem = useTabSystem(ws);
  const onToggleClipboardCollapse = useCallback(() => setClipboardCollapsed((v) => !v), [setClipboardCollapsed]);

  const tabRenderContext: TabRenderContext = {
    ws,
    activeTab: tabSystem.activeTab,
    siteStatus: tabSystem.siteStatus,
    fileChanges: tabSystem.fileChanges,
    sessionId: ws.sessionId,
    targetSessions,
    setTargetSessions,
    visibleCharacters,
    responseCharacters,
    onToggleAgentState,
    onToggleMessageVisibility: handleToggleMessageVisibility,
    setLightboxSrc,
    currentSessionArchived,
    clipboardCollapsed,
    onToggleClipboardCollapse,
    stageState,
    chatStyleCssText: chatStyleState.cssText,
    chatStyleStatus: chatStyleState.status,
    chatStyleReloadKey: chatStyleState.reloadKey,
    activeSubagentId,
    setActiveSubagentId,
  };

  const commandMenu = (
    <CommandMenu
      open={commandMenuOpen}
      onOpenChange={setCommandMenuOpen}
      sessionExportDisabled={exportDisabled || exportProcessing || sessionExport.busy}
      onOpenSessionExport={sessionExport.open}
      onOpenPerformanceTelemetry={() => setPerformanceTelemetryOpen(true)}
      stagePaused={stagePaused}
      onToggleStagePaused={() => setStagePaused((v) => !v)}
      stageStatusText={stageStatusText}
      chatStylePaused={chatStylePaused}
      onToggleChatStylePaused={() => setChatStylePaused((v) => !v)}
      chatStyleStatusText={chatStyleStatusText}
    />
  );
  const tabRailFooter = (
    <TabRailFooter
      hasSession={Boolean(ws.sessionId)}
      approvalMode={ws.approvalMode}
      approvalModeSyncStatus={ws.approvalModeSyncStatus}
      approvalModelAvailable={ws.approvalModelAvailable}
      approvalModelName={ws.approvalModelName}
      onSetApprovalMode={ws.setApprovalMode}
      commandMenu={commandMenu}
    />
  );
  const previewBlocked = performanceTelemetryOpen || !!lightboxSrc || onboardingRun
    || contextMenuOpen || sessionExport.isOpen || commandMenuOpen;

  return (
    <div className="app-layout">
      <Header
        status={ws.status}
        sessionId={ws.sessionId}
        sessionTitle={sessionTitle}
        tokenUsage={ws.tokenUsage}
        contextTokens={ws.contextTokens}
        llmMaxContextTokens={ws.llmMaxContextTokens}
        sidebarCollapsed={sidebarCollapsed}
        onToggleSidebar={() => setSidebarCollapsed((v) => !v)}
        agents={ws.agents}
        isMobile={isMobile}
        llmProfiles={ws.llmProfiles}
        modelMenuBlocked={performanceTelemetryOpen || !!lightboxSrc || onboardingRun || sessionExport.isOpen || commandMenuOpen}
      />
      <div className="app-body">
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
          forcePin={pinSidebar}
        />

        {isMobile && !sidebarCollapsed && (
          <div className="sidebar-backdrop" onClick={() => setSidebarCollapsed(true)} />
        )}

        <div className="main-content">
          <div className="tab-body">
            {ws.sessionLocked ? (
              <SessionLockOverlay onRetry={ws.retryConnect} />
            ) : (
              <TabDataProvider
                activeTab={tabSystem.activeTab}
                sessionId={ws.sessionId}
                currentSessionArchived={currentSessionArchived}
              >
                <TabStage
                  tabs={TAB_REGISTRY}
                  activeTab={tabSystem.activeTab}
                  renderContext={tabRenderContext}
                />
                <TabRail
                  tabs={TAB_REGISTRY}
                  activeTab={tabSystem.activeTab}
                  enabledTabs={tabSystem.enabledTabs}
                  onSwitch={tabSystem.switchTab}
                  renderContext={tabRenderContext}
                  previewBlocked={previewBlocked}
                  footer={tabRailFooter}
                />
              </TabDataProvider>
            )}
          </div>
        </div>
      </div>

      {lightboxSrc && (
        <Lightbox src={lightboxSrc} onClose={() => setLightboxSrc(null)} />
      )}

      {performanceTelemetryOpen && (
        <PerformanceTelemetryDialog onClose={() => setPerformanceTelemetryOpen(false)} />
      )}

      {sessionExport.isOpen && !ws.sessionLocked && <SessionExportDialog controller={sessionExport} />}
      {exportNotice && !sessionExport.isOpen && (
        <div className="session-export-notice">
          <NoticeBanner notice={{ kind: "error", message: exportNotice }} onDismiss={() => setExportNotice(null)} />
        </div>
      )}

      <OnboardingTour
        run={onboardingRun}
        onClose={onOnboardingClose}
        isMobile={isMobile}
        setSidebarCollapsed={setSidebarCollapsed}
        switchTab={tabSystem.switchTab}
        onPinSidebarChange={setPinSidebar}
      />
    </div>
  );
}
