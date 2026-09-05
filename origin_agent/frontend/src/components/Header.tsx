import { useRef, useState, useEffect } from "react";
import { useConnectionDiagnostics } from "../context/ConnectionDiagnosticsContext";
import { useEdgeDrawer } from "../hooks/useEdgeDrawer";
import { exportSession } from "../utils/exportSession";
import { COLLOQUY_SID } from "../constants/session";
import { TIMING } from "../constants/timing";
import type { LlmProfileManager } from "../hooks/useLlmProfiles";
import TokenRing from "./TokenRing";

interface HeaderProps {
  status: string;
  sessionId: string;
  tokenUsage: number;
  contextTokens: number;
  llmMaxContextTokens: number;
  handsfreeMode: boolean;
  yoloMode: boolean;
  approvalModelAvailable: boolean;
  approvalModelName: string;
  llmModelName: string;
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
  onToggleHandsfree: (enabled: boolean) => void;
  agents?: string[];
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  isMobile?: boolean;
  llmProfiles?: LlmProfileManager;
}

export default function Header({
  status,
  sessionId,
  tokenUsage,
  contextTokens,
  llmMaxContextTokens,
  handsfreeMode,
  yoloMode,
  approvalModelAvailable,
  approvalModelName,
  llmModelName,
  sidebarCollapsed,
  onToggleSidebar,
  onToggleHandsfree,
  agents,
  collapsed,
  onToggleCollapse,
  isMobile,
  llmProfiles,
}: HeaderProps) {
  const [cmdMenuOpen, setCmdMenuOpen] = useState(false);
  const [menuPos, setMenuPos] = useState<{ top: number; left: number } | null>(null);
  const cmdBtnRef = useRef<HTMLButtonElement>(null);
  // 桌面端顶部抽屉状态机；菜单展开期间钉住，断点切到移动端时强制归位
  const drawer = useEdgeDrawer({ active: !isMobile, pinned: cmdMenuOpen });

  useEffect(() => {
    if (!cmdMenuOpen) return;
    const onClick = (e: MouseEvent) => {
      const target = e.target as Node;
      if (cmdBtnRef.current?.contains(target)) return;
      setCmdMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setCmdMenuOpen(false);
    };
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("click", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [cmdMenuOpen]);

  const toggleCmdMenu = () => {
    setCmdMenuOpen((open) => {
      if (open) {
        setMenuPos(null);
        return false;
      }
      const rect = cmdBtnRef.current?.getBoundingClientRect();
      if (rect) {
        setMenuPos({ top: rect.bottom + 6, left: rect.left });
      }
      return true;
    });
  };

  const showHandsfreeToggle = yoloMode || approvalModelAvailable;

  // 移动端折叠态：只显示精简条
  if (isMobile && collapsed) {
    return (
      <header className="app-header app-header-collapsed">
        <div className="header-left">
          <button
            className="sidebar-toggle"
            onClick={onToggleSidebar}
            data-tooltip={sidebarCollapsed ? "展开侧栏" : "收起侧栏"}
          >
            {sidebarCollapsed ? (
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M9 18l6-6-6-6" />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M15 18l-6-6 6-6" />
              </svg>
            )}
          </button>
        </div>
        <div className="header-center">
          <div
            className={["header-pill", status === "已连接" ? "connected" : "", status.startsWith("重连中") ? "reconnecting" : "", status === "已断开" || status === "连接失败 — 已达到最大重试次数" ? "disconnected" : ""].filter(Boolean).join(" ")}
          >
            <span className="pill-label">Evolve Agent</span>
          </div>
        </div>
        <div className="header-right">
          <button
            className="header-collapse-btn"
            onClick={onToggleCollapse}
            data-tooltip="展开顶部栏"
          >
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 15l-6-6-6 6" />
            </svg>
          </button>
        </div>
      </header>
    );
  }

  // 桌面端：顶部覆盖抽屉——常驻 pill + 热区召唤的滑出 bar
  if (!isMobile) {
    return (
      <div className="header-layer">
        <div className="header-hotzone" {...drawer.hotzoneProps} />
        <div className="header-pill-dock">
          <HeaderPill status={status} agents={agents} llmModelName={llmModelName} llmProfiles={llmProfiles} />
        </div>
        <header
          className={`app-header header-drawer header-drawer-${drawer.phase}`}
          {...drawer.drawerProps}
        >
          <div className="header-left">
            {sessionId && (
              <span className="session-badge" data-tooltip="刷新页面后自动恢复此会话">
                {sessionId === COLLOQUY_SID ? "随意聊聊" : sessionId}
              </span>
            )}
            <DebugBadges />
            <button
              ref={cmdBtnRef}
              className="header-action-btn"
              onClick={toggleCmdMenu}
              data-tooltip="命令菜单"
            >
              ⋮
            </button>
            {cmdMenuOpen && menuPos && (
              <div
                className="context-menu cmd-menu-dropdown"
                style={{ position: "fixed", top: menuPos.top, left: menuPos.left }}
              >
                <div
                  className="context-menu-item"
                  onClick={() => {
                    setCmdMenuOpen(false);
                    setMenuPos(null);
                    exportSession(sessionId || "session");
                  }}
                  data-tooltip="导出当前会话为可分享的静态 HTML 文件"
                >
                  导出会话
                </div>
              </div>
            )}
          </div>

          {/* 中栏留空保持 1fr auto 1fr 网格平衡，pill 由 header-pill-dock 常驻 */}
          <div className="header-center" />

          {sessionId && (
            <div className="header-right">
              {showHandsfreeToggle && (
                <span
                  className={[
                    "approval-model-badge",
                    (yoloMode || handsfreeMode) ? "handsfree-on" : "handsfree-off",
                  ].filter(Boolean).join(" ")}
                  data-tooltip={yoloMode ? "YOLO 模式已开启 — 所有工具调用自动批准，不可关闭" : handsfreeMode ? "脱手模式已开启 — 工具调用由 AI 自动审批" : "脱手模式已关闭 — 工具调用需用户审批"}
                  onClick={yoloMode ? undefined : () => onToggleHandsfree(!handsfreeMode)}
                >
                  {yoloMode ? "AUTO" : handsfreeMode ? approvalModelName || "自动审批" : "脱手"}
                </span>
              )}
              <span className="token-badge" data-tooltip={`累计消耗: ${tokenUsage.toLocaleString()}  |  已用上下文: ${contextTokens.toLocaleString()}  |  最大上下文: ${llmMaxContextTokens > 0 ? llmMaxContextTokens.toLocaleString() : "?"}`}>
                累计 {tokenUsage.toLocaleString()} / 上下文 {contextTokens.toLocaleString()} / 上限 {llmMaxContextTokens > 0 ? llmMaxContextTokens.toLocaleString() : "?"}
              </span>
              <TokenRing
                contextTokens={contextTokens}
                llmMaxContextTokens={llmMaxContextTokens}
                tokenUsage={tokenUsage}
              />
            </div>
          )}
        </header>
      </div>
    );
  }

  // 移动端全量（未折叠）：流内 header
  return (
    <header className={`app-header ${isMobile && collapsed ? "app-header-collapsed" : ""}`}>
      <div className="header-left">
        {isMobile && (
          <button
            className="sidebar-toggle"
            onClick={onToggleSidebar}
            data-tooltip={sidebarCollapsed ? "展开侧栏" : "收起侧栏"}
          >
            {sidebarCollapsed ? (
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M9 18l6-6-6-6" />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M15 18l-6-6 6-6" />
              </svg>
            )}
          </button>
        )}
        {sessionId && (
          <span className="session-badge" data-tooltip="刷新页面后自动恢复此会话">
            {sessionId === COLLOQUY_SID ? "随意聊聊" : sessionId}
          </span>
        )}
        <DebugBadges />
        <button
          ref={cmdBtnRef}
          className="header-action-btn"
          onClick={toggleCmdMenu}
          data-tooltip="命令菜单"
        >
          ⋮
        </button>
        {cmdMenuOpen && menuPos && (
          <div
            className="context-menu cmd-menu-dropdown"
            style={{ position: "fixed", top: menuPos.top, left: menuPos.left }}
          >
            <div
              className="context-menu-item"
              onClick={() => {
                setCmdMenuOpen(false);
                setMenuPos(null);
                exportSession(sessionId || "session");
              }}
              data-tooltip="导出当前会话为可分享的静态 HTML 文件"
            >
              导出会话
            </div>
          </div>
        )}
      </div>

      <div className="header-center">
        <HeaderPill status={status} agents={agents} llmModelName={llmModelName} llmProfiles={llmProfiles} />
      </div>

      {sessionId && (
        <div className="header-right">
          {showHandsfreeToggle && (
            <span
              className={[
                "approval-model-badge",
                (yoloMode || handsfreeMode) ? "handsfree-on" : "handsfree-off",
              ].filter(Boolean).join(" ")}
              data-tooltip={yoloMode ? "YOLO 模式已开启 — 所有工具调用自动批准，不可关闭" : handsfreeMode ? "脱手模式已开启 — 工具调用由 AI 自动审批" : "脱手模式已关闭 — 工具调用需用户审批"}
              onClick={yoloMode ? undefined : () => onToggleHandsfree(!handsfreeMode)}
            >
              {yoloMode ? "AUTO" : handsfreeMode ? approvalModelName || "自动审批" : "脱手"}
            </span>
          )}
          <span className="token-badge" data-tooltip={`累计消耗: ${tokenUsage.toLocaleString()}  |  已用上下文: ${contextTokens.toLocaleString()}  |  最大上下文: ${llmMaxContextTokens > 0 ? llmMaxContextTokens.toLocaleString() : "?"}`}>
            累计 {tokenUsage.toLocaleString()} / 上下文 {contextTokens.toLocaleString()} / 上限 {llmMaxContextTokens > 0 ? llmMaxContextTokens.toLocaleString() : "?"}
          </span>
          <TokenRing
            contextTokens={contextTokens}
            llmMaxContextTokens={llmMaxContextTokens}
            tokenUsage={tokenUsage}
          />
        </div>
      )}
      {isMobile && onToggleCollapse && (
        <button
          className="header-collapse-btn"
          onClick={onToggleCollapse}
          data-tooltip="收起顶部栏"
        >
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M6 9l6 6 6-6" />
          </svg>
        </button>
      )}
    </header>
  );
}

function HeaderPill({
  status,
  agents,
  llmModelName,
  llmProfiles,
}: {
  status: string;
  agents?: string[];
  llmModelName: string;
  llmProfiles?: LlmProfileManager;
}) {
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!dropdownOpen) return;
    const onClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, [dropdownOpen]);

  return (
    <div
      ref={containerRef}
      className={[
        "header-pill",
        status === "已连接" ? "connected" : "",
        status.startsWith("重连中") ? "reconnecting" : "",
        status === "已断开" || status === "连接失败 — 已达到最大重试次数" ? "disconnected" : "",
        agents && agents.length > 0 ? "multi-agent" : "",
      ].filter(Boolean).join(" ")}
      data-tooltip={agents && agents.length > 0 ? `Multi-Agent 模式 · Agents: ${agents.join(", ")}` : undefined}
    >
      <span className="pill-label">{agents && agents.length > 0 ? "Evolve Agent · Multi" : "Evolve Agent"}</span>
      <span className="pill-detail">
        <span className="pill-status">{status}</span>
        {llmModelName ? (
          <span
            className={`pill-model${llmProfiles ? " pill-model-clickable" : ""}`}
            onClick={llmProfiles ? () => setDropdownOpen((v) => !v) : undefined}
            data-tooltip={llmProfiles ? "点击切换模型配置" : undefined}
          >
            {llmModelName}
          </span>
        ) : (
          <span
            className={`pill-model${llmProfiles ? " pill-model-clickable" : ""}`}
            onClick={llmProfiles ? () => setDropdownOpen((v) => !v) : undefined}
            data-tooltip={llmProfiles ? "点击配置模型" : undefined}
          >
            未配置模型
          </span>
        )}
        {agents && agents.length > 0 && <span className="pill-agent-count">{agents.length} agents</span>}
      </span>
      {dropdownOpen && llmProfiles && (
        <div className="pill-model-dropdown">
          {llmProfiles.profiles.map((p) => (
            <div
              key={p.name}
              className={`pill-model-option${p.name === llmProfiles.activeProfileName ? " active" : ""}`}
              onClick={(e) => {
                e.stopPropagation();
                llmProfiles.setActiveProfile(p.name);
                setDropdownOpen(false);
              }}
            >
              <span className="pill-model-option-name">
                {p.name}
              </span>
              <span className="pill-model-option-model">{p.model}</span>
            </div>
          ))}
        </div>
      )}
      <span className="pill-ripple" aria-hidden />
      <span className="pill-ripple" aria-hidden />
    </div>
  );
}

function DebugBadges() {
  const { waiting, pendingConfirm, streamingMessage, ignoreStaleRef, lastRecvAtRef, lastPongAtRef, recvTick, now } =
    useConnectionDiagnostics();

  const lastRecv = lastRecvAtRef?.current ?? now;
  const lastPong = lastPongAtRef?.current ?? now;
  const recvStall = now - lastRecv;
  const pongStall = now - lastPong;
  const active = waiting || !!streamingMessage;
  const recvStallThreshold = active ? TIMING.RECV_STALL_ACTIVE : TIMING.RECV_STALL_INACTIVE;

  return (
    <span className="debug-badges" key={recvTick}>
      {waiting && (
        <span className="debug-badge pulse" title="waiting=true">
          处理中 ⚡
        </span>
      )}
      {streamingMessage && (
        <span className="debug-badge ok" title={`stream id=${streamingMessage.id}`}>
          流式 ✍️
        </span>
      )}
      {pendingConfirm && (
        <span className="debug-badge danger" title={`confirm id=${pendingConfirm.request_id}`}>
          待审批 ⏳
        </span>
      )}
      {ignoreStaleRef?.current && (
        <span className="debug-badge warn" title="ignoreStaleRef=true">
          IGN
        </span>
      )}
      {recvStall >= recvStallThreshold ? (
        <span className="debug-badge danger" title={`last recv ${(recvStall / 1000).toFixed(1)}s ago`}>
          接收停滞 🛑 {Math.floor(recvStall / 1000)}s
        </span>
      ) : (
        <span className="debug-badge ok" title={`last recv ${recvStall}ms ago`}>
          接收正常
        </span>
      )}
      {pongStall >= TIMING.PONG_STALL && (
        <span className="debug-badge warn" title={`last pong ${(pongStall / 1000).toFixed(1)}s ago`}>
          心跳异常
        </span>
      )}
    </span>
  );
}
