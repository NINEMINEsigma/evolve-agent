import { useEffect, useRef, useState } from "react";

interface HeaderProps {
  status: string;
  sessionId: string;
  tokenUsage: number;
  contextTokens: number;
  llmMaxContextTokens: number;
  handsfreeMode: boolean;
  approvalModelAvailable: boolean;
  approvalModelName: string;
  llmModelName: string;
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
  onToggleHandsfree: (enabled: boolean) => void;
  waiting?: boolean;
  pendingConfirm?: { request_id: string } | null;
  streamingMessage?: { id: string } | null;
  ignoreStaleRef?: React.RefObject<boolean>;
  lastRecvAtRef?: React.RefObject<number>;
  lastPongAtRef?: React.RefObject<number>;
  recvTick?: number;
  agents?: string[];
}

export default function Header({
  status,
  sessionId,
  tokenUsage,
  contextTokens,
  llmMaxContextTokens,
  handsfreeMode,
  approvalModelAvailable,
  approvalModelName,
  llmModelName,
  sidebarCollapsed,
  onToggleSidebar,
  onToggleHandsfree,
  waiting,
  pendingConfirm,
  streamingMessage,
  ignoreStaleRef,
  lastRecvAtRef,
  lastPongAtRef,
  recvTick,
  agents,
}: HeaderProps) {
  const [cmdMenuOpen, setCmdMenuOpen] = useState(false);
  const [menuPos, setMenuPos] = useState<{ top: number; left: number } | null>(null);
  const [modelClosed, setModelClosed] = useState(false);
  const [shuttingDown, setShuttingDown] = useState(false);
  const cmdBtnRef = useRef<HTMLButtonElement>(null);

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

  const handleShutdownApprovalModel = async () => {
    setCmdMenuOpen(false);
    setMenuPos(null);
    if (!window.confirm("确定要关闭审批模型 (llama-server) 吗？关闭后将释放显存，脱手模式不可用。")) return;
    setShuttingDown(true);
    try {
      const resp = await fetch("/api/shutdown-approval-model", { method: "POST" });
      const data = await resp.json();
      if (data.ok) {
        setModelClosed(true);
        onToggleHandsfree(false);
        alert("审批模型已关闭，显存已释放。");
      } else {
        alert("关闭审批模型失败。");
      }
    } catch {
      alert("请求失败，请检查网络。");
    } finally {
      setShuttingDown(false);
    }
  };

  const showApprovalUI = approvalModelAvailable && !modelClosed;

  return (
    <header className="app-header">
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
        {sessionId && (
          <span className="session-badge" data-tooltip="刷新页面后自动恢复此会话">
            {sessionId}
          </span>
        )}
        <DebugBadges
          waiting={waiting}
          pendingConfirm={pendingConfirm}
          streamingMessage={streamingMessage}
          ignoreStaleRef={ignoreStaleRef}
          lastRecvAtRef={lastRecvAtRef}
          lastPongAtRef={lastPongAtRef}
          recvTick={recvTick}
        />
        <button
          ref={cmdBtnRef}
          className="header-action-btn"
          onClick={toggleCmdMenu}
          data-tooltip="命令菜单"
          disabled={shuttingDown}
        >
          ⋮
        </button>
        {cmdMenuOpen && menuPos && (
          <div
            className="context-menu cmd-menu-dropdown"
            style={{ position: "fixed", top: menuPos.top, left: menuPos.left }}
          >
            <div
              className={`context-menu-item ${showApprovalUI ? "context-menu-item-danger" : ""}`}
              onClick={showApprovalUI ? handleShutdownApprovalModel : undefined}
              style={showApprovalUI ? undefined : { opacity: 0.45, cursor: "not-allowed", userSelect: "none" }}
              data-tooltip={showApprovalUI ? "" : "审批模型未加载"}
            >
              关闭审批模型
            </div>
          </div>
        )}
      </div>

      <div className="header-center">
        <div
          className={[
            "header-pill",
            status === "已连接" ? "connected" : "",
            status.startsWith("重连中") ? "reconnecting" : "",
            status === "已断开" || status === "连接失败 — 已达到最大重试次数" ? "disconnected" : "",
            agents && agents.length > 0 ? "multi-agent" : "",
          ].filter(Boolean).join(" ")}
          data-tooltip={agents && agents.length > 0 ? `Multi-Agent 模式 · Agents: ${agents.join(", ")}` : undefined}
        >
          <span className="status-dot" />
          <span className="pill-label">{agents && agents.length > 0 ? "Evolve Agent · Multi" : "Evolve Agent"}</span>
          <span className="pill-detail">
            <span className="pill-status">{status}</span>
            {llmModelName && <span className="pill-model">{llmModelName}</span>}
            {agents && agents.length > 0 && <span className="pill-agent-count">{agents.length} agents</span>}
          </span>
          <span className="pill-ripple" aria-hidden />
          <span className="pill-ripple" aria-hidden />
        </div>
      </div>

      {sessionId && (
        <div className="header-right">
          {showApprovalUI && (
            <span
              className={[
                "approval-model-badge",
                handsfreeMode ? "handsfree-on" : "handsfree-off",
              ].filter(Boolean).join(" ")}
              data-tooltip={handsfreeMode ? "脱手模式已开启 — 工具调用由 AI 自动审批" : "脱手模式已关闭 — 工具调用需用户审批"}
              onClick={() => onToggleHandsfree(!handsfreeMode)}
            >
              {handsfreeMode ? approvalModelName || "自动审批" : "脱手"}
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
  );
}

function DebugBadges({
  waiting,
  pendingConfirm,
  streamingMessage,
  ignoreStaleRef,
  lastRecvAtRef,
  lastPongAtRef,
  recvTick,
}: {
  waiting?: boolean;
  pendingConfirm?: { request_id: string } | null;
  streamingMessage?: { id: string } | null;
  ignoreStaleRef?: React.RefObject<boolean>;
  lastRecvAtRef?: React.RefObject<number>;
  lastPongAtRef?: React.RefObject<number>;
  recvTick?: number;
})
{
  const [, forceRender] = useState(0);
  useEffect(() => {
    const id = setInterval(() => forceRender((v) => v + 1), 500);
    return () => clearInterval(id);
  }, []);

  const now = Date.now();
  const lastRecv = lastRecvAtRef?.current ?? now;
  const lastPong = lastPongAtRef?.current ?? now;
  const recvStall = now - lastRecv;
  const pongStall = now - lastPong;
  const active = waiting || !!streamingMessage;
  const recvStallThreshold = active ? 2000 : 30000;

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
      {pongStall >= 35000 && (
        <span className="debug-badge warn" title={`last pong ${(pongStall / 1000).toFixed(1)}s ago`}>
          心跳异常
        </span>
      )}
    </span>
  );
}

function TokenRing({
  contextTokens,
  llmMaxContextTokens,
  tokenUsage,
}: {
  contextTokens: number;
  llmMaxContextTokens: number;
  tokenUsage: number;
}) {
  const percent =
    llmMaxContextTokens > 0
      ? Math.round((contextTokens / llmMaxContextTokens) * 100)
      : 0;
  const R = 12;
  const C = 2 * Math.PI * R;
  const offset = C * (1 - percent / 100);

  return (
    <span
      className="token-ring"
      data-tooltip={`累计消耗: ${tokenUsage.toLocaleString()}  |  已用上下文: ${contextTokens.toLocaleString()}  |  最大上下文: ${llmMaxContextTokens > 0 ? llmMaxContextTokens.toLocaleString() : "?"}`}
    >
      <svg viewBox="0 0 32 32" width="28" height="28">
        <circle
          className="token-ring-track"
          cx="16"
          cy="16"
          r={R}
        />
        <circle
          className="token-ring-progress"
          cx="16"
          cy="16"
          r={R}
          style={{ strokeDashoffset: offset }}
        />
      </svg>
      <span className="token-ring-label">{percent}</span>
    </span>
  );
}