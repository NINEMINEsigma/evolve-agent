import { useEffect, useRef, useState } from "react";
import type { MessageContent } from "../types";
import { CHAT_TOP_SAFE_SPACE_PX } from "../constants/history";
import { DIMENSIONS } from "../constants/dimensions";
import Minimap from "./Minimap";
import AgentStageLayer from "./AgentStageLayer";
import ChatStyleLayer from "./ChatStyleLayer";
import VirtualMessageList, { type ChatVirtualListHandle } from "../features/chat/VirtualMessageList";
import { useChatRuntimeStore } from "../features/chat/chatRuntimeStore";
import type { ChatStyleStatus } from "../hooks/useSessionChatStyle";
import type { SessionStageState } from "../hooks/useSessionStage";

interface ChatAreaProps {
  archived: boolean;
  onImageClick: (src: string) => void;
  onEditMessage: (id: string, content: MessageContent) => void | Promise<void>;
  onDeleteMessages: (count: number) => void;
  onDeleteSingleMessage?: (index: number) => void;
  onRegenerateResponse: (messageIndex: number) => void;
  onDropFiles: (files: FileList) => void;
  agents?: string[];
  onToggleMessageVisibility?: (messageId: string, agentName: string) => void;
  children?: React.ReactNode;
  stageState: SessionStageState;
  chatStyleCssText?: string | null;
  chatStyleStatus?: ChatStyleStatus;
  chatStyleReloadKey?: number;
}

export default function ChatArea({
  archived,
  onImageClick,
  onEditMessage,
  onDeleteMessages,
  onDeleteSingleMessage,
  onRegenerateResponse,
  onDropFiles,
  agents,
  onToggleMessageVisibility,
  children,
  stageState,
  chatStyleCssText,
  chatStyleStatus,
  chatStyleReloadKey,
}: ChatAreaProps) {
  const isMobileQuery = `(max-width: ${DIMENSIONS.MOBILE_BREAKPOINT}px)`;
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== "undefined" && window.matchMedia(isMobileQuery).matches,
  );
  const [minimapCollapsed, setMinimapCollapsed] = useState(() =>
    typeof window !== "undefined" && window.matchMedia(isMobileQuery).matches,
  );
  const listRef = useRef<ChatVirtualListHandle>(null);
  const followMode = useChatRuntimeStore((state) => state.followMode);
  const skeletonLength = useChatRuntimeStore((state) => state.skeleton.length);
  const liveLength = useChatRuntimeStore((state) => state.liveRows.length);
  const processing = useChatRuntimeStore((state) => state.processing);
  const isEmpty = skeletonLength === 0 && liveLength === 0 && !processing;
  const topSafeSpacePx = isMobile ? 0 : CHAT_TOP_SAFE_SPACE_PX;

  useEffect(() => {
    const media = window.matchMedia(isMobileQuery);
    const onChange = (event: MediaQueryListEvent) => {
      setIsMobile(event.matches);
      setMinimapCollapsed(event.matches);
    };
    setIsMobile(media.matches);
    setMinimapCollapsed(media.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [isMobileQuery]);

  return (
    <div className="chat-area-wrapper">
      <div className={`chat-area-container${isEmpty ? " chat-area-container-empty" : ""}`}>
        <AgentStageLayer stageState={stageState} />
        <ChatStyleLayer
          cssText={chatStyleCssText ?? null}
          status={chatStyleStatus ?? "idle"}
          reloadKey={chatStyleReloadKey ?? 0}
        />
        <VirtualMessageList
          ref={listRef}
          archived={archived}
          onImageClick={onImageClick}
          onEditMessage={onEditMessage}
          onDeleteMessages={onDeleteMessages}
          onDeleteSingleMessage={onDeleteSingleMessage}
          onRegenerateResponse={onRegenerateResponse}
          onDropFiles={onDropFiles}
          agents={agents}
          onToggleMessageVisibility={onToggleMessageVisibility}
          topSafeSpacePx={topSafeSpacePx}
        />
        {followMode === "detached" && (
          <button
            type="button"
            className="scroll-to-bottom"
            onClick={() => void listRef.current?.returnToBottom()}
            aria-label="回到最新位置"
            title="回到最新位置"
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </button>
        )}
        {children}
      </div>
      {!minimapCollapsed && (
        <Minimap
          topSafeSpacePx={topSafeSpacePx}
          onDragStart={() => listRef.current?.beginMinimapDrag()}
          onPreviewScrollTop={(scrollTop) => listRef.current?.previewMinimapScrollTop(scrollTop)}
          onDragEnd={(scrollTop) => listRef.current?.commitMinimapDrag(scrollTop)}
        />
      )}
      <button
        type="button"
        className="minimap-toggle"
        onClick={() => setMinimapCollapsed((value) => !value)}
        aria-label={minimapCollapsed ? "展开预览条" : "收起预览条"}
        title={minimapCollapsed ? "展开预览条" : "收起预览条"}
      >
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2">
          {minimapCollapsed ? <path d="M15 18l-6-6 6-6" /> : <path d="M9 18l6-6-6-6" />}
        </svg>
      </button>
    </div>
  );
}
