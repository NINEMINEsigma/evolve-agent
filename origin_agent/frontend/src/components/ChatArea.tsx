import { useEffect, useMemo, useRef, useState } from "react";
import type { MessageContent } from "../types";
import { CHAT_TOP_SAFE_SPACE_PX } from "../constants/history";
import { DIMENSIONS } from "../constants/dimensions";
import { ROUND_NAV_JUMP_OFFSET_RATIO } from "../constants/roundNav";
import RoundNavRail from "./RoundNavRail";
import AgentStageLayer from "./AgentStageLayer";
import ChatStyleLayer from "./ChatStyleLayer";
import VirtualMessageList, { type ChatVirtualListHandle } from "../features/chat/VirtualMessageList";
import { selectChatRenderRows, useChatRuntimeStore } from "../features/chat/chatRuntimeStore";
import { buildRoundNavEntries, resolveCurrentRoundEntryId } from "../features/chat/roundNav";
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
  const listRef = useRef<ChatVirtualListHandle>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const runtime = useChatRuntimeStore();
  const followMode = runtime.followMode;
  const initialReady = runtime.initialReady;
  const atBottom = runtime.atBottom;
  const renderRows = selectChatRenderRows(runtime);
  const processing = runtime.processing;
  const isEmpty = renderRows.length === 0 && !processing;
  const topSafeSpacePx = isMobile ? 0 : CHAT_TOP_SAFE_SPACE_PX;
  const roundNavEntries = useMemo(() => buildRoundNavEntries(renderRows), [renderRows]);
  const renderRowIndexById = useMemo(() => {
    const map = new Map<string, number>();
    renderRows.forEach((row, index) => map.set(row.renderId, index));
    return map;
  }, [renderRows]);
  const [currentRoundEntryId, setCurrentRoundEntryId] = useState<string | null>(null);
  const scrollMetrics = runtime.scrollMetrics;

  // 当前轮：已渲染行中最后一个顶部位于「视口顶 + 跳转偏移比例」参考线以上的行所归属的条目。
  // 用 DOM 参考线而不是渲染范围索引，避免 overscan 把当前轮解析到视口之外的前一条。
  useEffect(() => {
    const scroller = wrapperRef.current?.querySelector<HTMLElement>(".chat-area");
    if (!scroller || roundNavEntries.length === 0) {
      setCurrentRoundEntryId(null);
      return;
    }
    const scrollerRect = scroller.getBoundingClientRect();
    const reference = scrollerRect.top + scroller.clientHeight * ROUND_NAV_JUMP_OFFSET_RATIO;
    const rowElements = scroller.querySelectorAll<HTMLElement>("[data-render-row-id]");
    let referenceRowIndex = 0;
    for (const element of rowElements) {
      if (element.getBoundingClientRect().top > reference) break;
      const rowIndex = renderRowIndexById.get(element.dataset.renderRowId || "");
      if (rowIndex !== undefined) referenceRowIndex = rowIndex;
    }
    const next = resolveCurrentRoundEntryId(roundNavEntries, referenceRowIndex);
    setCurrentRoundEntryId((previous) => (previous === next ? previous : next));
  }, [scrollMetrics, roundNavEntries, renderRowIndexById]);

  useEffect(() => {
    const media = window.matchMedia(isMobileQuery);
    const onChange = (event: MediaQueryListEvent) => {
      setIsMobile(event.matches);
    };
    setIsMobile(media.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [isMobileQuery]);

  return (
    <div className="chat-area-wrapper" ref={wrapperRef}>
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
        {!isEmpty && initialReady && !atBottom
          && followMode !== "initializing" && followMode !== "returning" && (
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
      <RoundNavRail
        entries={roundNavEntries}
        currentEntryId={currentRoundEntryId}
        onJump={(entry) => void listRef.current?.jumpToRound(entry.rowIndex)}
      />
    </div>
  );
}
