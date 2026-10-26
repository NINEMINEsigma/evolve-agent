import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import PopupLayer from "./primitives/PopupLayer";
import { useChatRuntimeStore } from "../features/chat/chatRuntimeStore";
import { exportLabels } from "../features/sessionExport/labels";

export interface CommandMenuProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sessionExportDisabled: boolean;
  onOpenSessionExport: () => void;
  onOpenPerformanceTelemetry: () => void;
  stagePaused: boolean;
  onToggleStagePaused: () => void;
  stageStatusText: string;
  chatStylePaused: boolean;
  onToggleChatStylePaused: () => void;
  chatStyleStatusText: string;
}

type CloseReason = "toggle" | "escape" | "menu-item" | "outside" | "scope-change";

export default function CommandMenu({
  open,
  onOpenChange,
  sessionExportDisabled,
  onOpenSessionExport,
  onOpenPerformanceTelemetry,
  stagePaused,
  onToggleStagePaused,
  stageStatusText,
  chatStylePaused,
  onToggleChatStylePaused,
  chatStyleStatusText,
}: CommandMenuProps) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [position, setPosition] = useState<{ x: number; y: number } | null>(null);
  const excludeRefs = useMemo(() => [triggerRef], []);
  const showSystemUserMessages = useChatRuntimeStore((state) => state.showSystemUserMessages);
  const setShowSystemUserMessages = useChatRuntimeStore((state) => state.setShowSystemUserMessages);

  const updatePosition = useCallback(() => {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (!rect) return;
    setPosition({ x: rect.right, y: rect.top });
  }, []);

  const close = useCallback((reason: CloseReason) => {
    onOpenChange(false);
    setPosition(null);
    if (reason !== "outside" && reason !== "scope-change") {
      triggerRef.current?.focus();
    }
  }, [onOpenChange]);

  useLayoutEffect(() => {
    if (!open) {
      setPosition(null);
      return;
    }
    updatePosition();
    const viewport = window.visualViewport;
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    viewport?.addEventListener("resize", updatePosition);
    viewport?.addEventListener("scroll", updatePosition);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
      viewport?.removeEventListener("resize", updatePosition);
      viewport?.removeEventListener("scroll", updatePosition);
    };
  }, [open, updatePosition]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close("escape");
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [close, open]);

  const handleToggle = () => {
    if (open) {
      close("toggle");
      return;
    }
    onOpenChange(true);
  };

  const closeForMenuItem = (action: () => void) => {
    close("scope-change");
    action();
  };

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="header-action-btn tab-rail-footer-button tab-rail-command-button"
        onClick={handleToggle}
        data-tooltip="命令菜单"
        aria-label="命令菜单"
        aria-expanded={open}
      >
        ⋮
      </button>
      {open && position && (
        <PopupLayer
          position={position}
          onClose={() => close("outside")}
          closeOnEsc={false}
          className="context-menu cmd-menu-dropdown"
          style={{ transform: "translate(-100%, -100%)" }}
          excludeRefs={excludeRefs}
        >
          <button
            type="button"
            className="context-menu-item session-export-menu-button"
            disabled={sessionExportDisabled}
            data-tooltip={sessionExportDisabled ? exportLabels.busy : exportLabels.offline}
            onClick={() => closeForMenuItem(onOpenSessionExport)}
          >
            {exportLabels.title}
          </button>
          <button
            type="button"
            className="context-menu-item"
            onClick={() => closeForMenuItem(onOpenPerformanceTelemetry)}
            data-tooltip="打开本地聊天性能遥测"
          >
            性能遥测
          </button>
          <button
            type="button"
            role="switch"
            aria-checked={showSystemUserMessages}
            aria-label="显示 system 角色用户消息"
            className="context-menu-item context-menu-toggle"
            onClick={() => setShowSystemUserMessages(!showSystemUserMessages)}
            data-tooltip="仅切换 system 角色用户消息的显示，不影响历史记录、模型上下文和系统状态提示"
          >
            system 角色用户消息：{showSystemUserMessages ? "显示" : "隐藏"}
          </button>
          <button
            type="button"
            className="context-menu-item"
            onClick={onToggleStagePaused}
            data-tooltip={stageStatusText === "未配置" ? "Agent 舞台层未配置" : stagePaused ? "恢复 Agent 舞台层" : "暂停 Agent 舞台层"}
          >
            Agent 舞台层：{stageStatusText}
          </button>
          <button
            type="button"
            className="context-menu-item"
            onClick={onToggleChatStylePaused}
            data-tooltip={chatStyleStatusText === "未配置" ? "聊天区自定义样式未配置" : chatStylePaused ? "恢复聊天区自定义样式" : "暂停聊天区自定义样式"}
          >
            聊天区样式：{chatStyleStatusText}
          </button>
        </PopupLayer>
      )}
    </>
  );
}
