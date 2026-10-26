import { useCallback, useEffect, useId, useRef, useState } from "react";
import ModelProfileMenu from "./ModelProfileMenu";
import SessionIdentity from "./SessionIdentity";
import ContextProgressBadge from "./ContextProgressBadge";
import ConnectionStatusLight from "./ConnectionStatusLight";
import type { LlmProfileManager } from "../hooks/useLlmProfiles";

interface HeaderProps {
  status: string;
  sessionId: string;
  sessionTitle: string;
  tokenUsage: number;
  contextTokens: number;
  llmMaxContextTokens: number;
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
  agents?: string[];
  isMobile?: boolean;
  llmProfiles?: LlmProfileManager;
  modelMenuBlocked?: boolean;
}

export default function Header({
  status,
  sessionId,
  sessionTitle,
  tokenUsage,
  contextTokens,
  llmMaxContextTokens,
  sidebarCollapsed,
  onToggleSidebar,
  isMobile = false,
  llmProfiles,
  modelMenuBlocked = false,
}: HeaderProps) {
  return (
    <header className="app-header" data-tour="header">
      <div className="header-session-area">
        {isMobile && (
          <button
            className="sidebar-toggle"
            onClick={onToggleSidebar}
            data-tooltip={sidebarCollapsed ? "展开侧栏" : "收起侧栏"}
            aria-label={sidebarCollapsed ? "展开侧栏" : "收起侧栏"}
          >
            {sidebarCollapsed ? (
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M9 18l6-6-6-6" />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M15 18l-6-6 6-6" />
              </svg>
            )}
          </button>
        )}
        <SessionIdentity title={sessionTitle} sessionId={sessionId} />
      </div>
      <div className="header-trapezoid">
        <ContextProgressBadge
          contextTokens={contextTokens}
          llmMaxContextTokens={llmMaxContextTokens}
          tokenUsage={tokenUsage}
        />
        <HeaderPill
          status={status}
          llmModelName={llmProfiles?.activeProfile?.model ?? ""}
          llmProfiles={llmProfiles}
          modelMenuBlocked={modelMenuBlocked}
        />
        <ConnectionStatusLight status={status} />
      </div>
    </header>
  );
}

function HeaderPill({ status, llmModelName, llmProfiles, modelMenuBlocked = false }: {
  status: string;
  llmModelName: string;
  llmProfiles?: LlmProfileManager;
  modelMenuBlocked?: boolean;
}) {
  const [menuSession, setMenuSession] = useState<string | null>(null);
  const anchorRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();
  const sid = llmProfiles?.sessionId ?? "";
  const menuOpen = menuSession !== null && menuSession === sid && !modelMenuBlocked;
  const closeMenu = useCallback(() => setMenuSession(null), []);
  useEffect(() => { setMenuSession(null); }, [sid, modelMenuBlocked]);

  const profileLabel = llmProfiles?.selectionStatus === "loading"
    ? "读取中…"
    : llmProfiles?.selectionStatus === "error"
      ? "读取失败"
      : llmProfiles?.activeProfileName || llmModelName || "未配置";

  return (
    <div className={`header-pill ${menuOpen ? "header-pill--menu-open" : ""} ${status === "已断开" || status === "连接失败 — 已达到最大重试次数" ? "disconnected" : status.startsWith("重连中") ? "reconnecting" : ""}`}>
      {llmProfiles ? (
        <button
          type="button"
          ref={anchorRef}
          className="pill-profile-button"
          aria-expanded={menuOpen}
          aria-controls={menuId}
          aria-label={`${profileLabel}，选择当前会话待用模型`}
          disabled={modelMenuBlocked || !sid}
          onClick={() => setMenuSession((previous) => previous === sid ? null : sid)}
        >
          {profileLabel}
        </button>
      ) : (
        <span className="pill-profile-label">{profileLabel}</span>
      )}
      {llmProfiles && <ModelProfileMenu open={menuOpen} anchorRef={anchorRef} manager={llmProfiles} onClose={closeMenu} />}
    </div>
  );
}
