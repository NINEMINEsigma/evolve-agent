import { useCallback, useEffect, useRef, useState } from "react";
import { useWebSocket } from "./hooks/useWebSocket";
import Sidebar from "./components/Sidebar";
import Header from "./components/Header";
import ChatArea from "./components/ChatArea";
import InputBar from "./components/InputBar";
import ConfirmDialog from "./components/ConfirmDialog";
import AskDialog from "./components/AskDialog";
import TaskProgressPanel from "./components/TaskProgressPanel";
import UnifiedPanel from "./components/UnifiedPanel";
import Drawer from "./components/Drawer";
import SubagentPanel from "./components/SubagentPanel";
import CronCountdown from "./components/CronCountdown";
import SubagentCountdown from "./components/SubagentCountdown";
import Lightbox from "./components/Lightbox";
import TagEditor from "./components/TagEditor";
import ErrorBoundary from "./components/ErrorBoundary";
import { SessionInfo } from "./types";

const TOOLTIP_MARGIN = 10;
const TOOLTIP_ARROW = 6;

function useGlobalTooltip() {
  useEffect(() => {
    const tooltip = document.createElement("div");
    tooltip.className = "global-tooltip";
    const arrow = document.createElement("div");
    arrow.className = "global-tooltip-arrow";
    tooltip.appendChild(arrow);
    document.body.appendChild(tooltip);

    let hideTimer: ReturnType<typeof setTimeout> | null = null;

    const showTooltip = (target: HTMLElement, text: string) => {
      if (hideTimer) {
        clearTimeout(hideTimer);
        hideTimer = null;
      }
      tooltip.textContent = text;
      tooltip.appendChild(arrow);
      tooltip.classList.add("visible");

      const rect = target.getBoundingClientRect();
      const tipRect = tooltip.getBoundingClientRect();
      const vw = window.innerWidth;
      const vh = window.innerHeight;

      let top = rect.bottom + TOOLTIP_MARGIN + TOOLTIP_ARROW;
      let left = rect.left + rect.width / 2 - tipRect.width / 2;
      let arrowDir: "top" | "bottom" | "left" | "right" = "top";

      if (top + tipRect.height > vh - TOOLTIP_MARGIN) {
        top = rect.top - tipRect.height - TOOLTIP_MARGIN - TOOLTIP_ARROW;
        arrowDir = "bottom";
      }
      if (left < TOOLTIP_MARGIN) {
        left = TOOLTIP_MARGIN;
      }
      if (left + tipRect.width > vw - TOOLTIP_MARGIN) {
        left = vw - tipRect.width - TOOLTIP_MARGIN;
      }

      if (tipRect.width > vw - TOOLTIP_MARGIN * 2) {
        left = TOOLTIP_MARGIN;
        tooltip.style.maxWidth = `${vw - TOOLTIP_MARGIN * 2}px`;
      }

      tooltip.style.top = `${top}px`;
      tooltip.style.left = `${left}px`;

      arrow.className = `global-tooltip-arrow ${arrowDir}`;
      if (arrowDir === "top") {
        arrow.style.top = "-5px";
        arrow.style.left = `${rect.left + rect.width / 2 - left - 5}px`;
        arrow.style.bottom = "";
        arrow.style.right = "";
      } else if (arrowDir === "bottom") {
        arrow.style.bottom = "-5px";
        arrow.style.left = `${rect.left + rect.width / 2 - left - 5}px`;
        arrow.style.top = "";
        arrow.style.right = "";
      }
    };

    const hideTooltip = () => {
      if (hideTimer) clearTimeout(hideTimer);
      hideTimer = setTimeout(() => {
        tooltip.classList.remove("visible");
      }, 80);
    };

    const onMouseEnter = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (!target) return;
      const tooltipText = target.getAttribute("data-tooltip");
      if (!tooltipText) return;
      showTooltip(target, tooltipText);
    };

    const onMouseLeave = () => {
      hideTooltip();
    };

    const app = document.getElementById("root");
    if (app) {
      app.addEventListener("mouseenter", onMouseEnter, true);
      app.addEventListener("mouseleave", onMouseLeave, true);
    }

    return () => {
      if (app) {
        app.removeEventListener("mouseenter", onMouseEnter, true);
        app.removeEventListener("mouseleave", onMouseLeave, true);
      }
      if (hideTimer) clearTimeout(hideTimer);
      tooltip.remove();
    };
  }, []);
}

export default function App() {
  useGlobalTooltip();
  const ws = useWebSocket();
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

  const onToggleAgentState = (agentName: string) => {
    // 先把 all-agents 展开为实际 agents
    let curVisible = visibleCharacters.includes("all-agents")
      ? ws.agents
      : [...visibleCharacters];
    let curResponse = [...responseCharacters];
    const vis = curVisible.includes(agentName);
    const res = curResponse.includes(agentName);

    if (!vis && !res) {
      // none -> visible only
      curVisible.push(agentName);
      curResponse = curResponse.filter((a) => a !== agentName);
    } else if (vis && !res) {
      // visible -> response
      if (!curResponse.includes(agentName)) curResponse.push(agentName);
    } else {
      // response -> none
      curVisible = curVisible.filter((a) => a !== agentName);
      curResponse = curResponse.filter((a) => a !== agentName);
    }
    // 如果全部可见则缩回 all-agents 简写
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
    // 展开 all-agents
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
    // 立即更新本地消息状态
    ws.setMessages((prev) => prev.map((m) =>
      m.id === messageId ? { ...m, visibleCharacters: newVisible, responseCharacters: curResponse } : m
    ));
  };

  // 切换主会话时重置目标选择为默认值（仅对没有记录的新会话生效）
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

  const [taskProgressCollapsed, setTaskProgressCollapsed] = useState(false);
  const [clipboardCollapsed, setClipboardCollapsed] = useState(false);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; sid: string } | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [tagEditorSession, setTagEditorSession] = useState<SessionInfo | null>(null);
  const [isMobile, setIsMobile] = useState(false);

  // ── 移动端默认折叠侧边栏 ──
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 768px)");
    const onChange = (e: MediaQueryListEvent) => {
      setIsMobile(e.matches);
      setSidebarCollapsed(e.matches);
    };
    setIsMobile(mq.matches);
    setSidebarCollapsed(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

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

  useEffect(() => {
    ws.fetchAllTags();
  }, []);

  useEffect(() => {
    const cleanup = ws.attachScrollListener();
    return cleanup;
  }, [ws.attachScrollListener, ws.chatAreaRef]);

  return (
    <ErrorBoundary>
      <div className="app">
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
        onContextMenu={handleContextMenu}
        onMergeSessions={(sources) => {
          ws.mergeSessions(sources);
          ws.setMergeMode(false);
          ws.setSelectedForMerge(new Set());
        }}
        sidebarSessions={ws.sidebarSessions}
      />

      {isMobile && !sidebarCollapsed && (
        <div
          className="sidebar-backdrop"
          onClick={() => setSidebarCollapsed(true)}
        />
      )}

      {contextMenu && (
        <div
          ref={menuRef}
          className="context-menu"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <div
            className={`context-menu-item ${ws.generatingTitleSessions.has(contextMenu.sid) ? "context-menu-item-disabled" : ""}`}
            onClick={() => {
              if (ws.generatingTitleSessions.has(contextMenu.sid)) return;
              setContextMenu(null);
              ws.autoTitleSession(contextMenu.sid);
            }}
          >
            {ws.generatingTitleSessions.has(contextMenu.sid) ? "⏳ 命名中..." : "自动命名"}
          </div>
          <div
            className={`context-menu-item ${ws.generatingTagSessions.has(contextMenu.sid) ? "context-menu-item-disabled" : ""}`}
            onClick={() => {
              if (ws.generatingTagSessions.has(contextMenu.sid)) return;
              setContextMenu(null);
              ws.autoTagSession(contextMenu.sid);
            }}
          >
            {ws.generatingTagSessions.has(contextMenu.sid) ? "⏳ 生成标签中..." : "自动标签"}
          </div>
          <div className="context-menu-item" onClick={() => { setContextMenu(null); ws.togglePinSession(contextMenu.sid); }}>
            {(() => {
              const s = ws.sessions.find((s) => s.id === contextMenu.sid);
              return s?.pinned ? "取消收藏" : "收藏";
            })()}
          </div>
          <div className="context-menu-item" onClick={() => { setContextMenu(null); setTagEditorSession(ws.sessions.find((s) => s.id === contextMenu.sid) || null); }}>
            编辑标签
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
          llmModelName={ws.llmModelName}
          sidebarCollapsed={sidebarCollapsed}
          onToggleSidebar={() => setSidebarCollapsed((v) => !v)}
          onToggleHandsfree={ws.toggleHandsfree}
          waiting={ws.waiting}
          pendingConfirm={ws.pendingConfirm}
          streamingMessage={ws.streamingMessage}
          ignoreStaleRef={ws.ignoreStaleRef}
          lastRecvAtRef={ws.lastRecvAtRef}
          lastPongAtRef={ws.lastPongAtRef}
          recvTick={ws.recvTick}
          agents={ws.agents}
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
          onDropFiles={ws.handleFileUpload}
          streamingMessage={ws.streamingMessage}
          agents={ws.agents}
          onToggleMessageVisibility={onToggleMessageVisibility}
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

      {tagEditorSession && (
        <TagEditor
          session={tagEditorSession}
          allTags={ws.allTags}
          onClose={() => setTagEditorSession(null)}
          onSave={async (sid, tags) => {
            await ws.updateSessionTags(sid, tags);
            ws.fetchAllTags();
          }}
        />
      )}
      </div>
    </ErrorBoundary>
  );
}
