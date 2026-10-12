import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  Virtuoso,
  type Components,
  type ListItem,
  type ListRange,
  type VirtuosoHandle,
} from "react-virtuoso";
import type { MessageContent } from "../../types";
import {
  HISTORY_SCROLL_SEEK_ENTER,
  HISTORY_SCROLL_SEEK_EXIT,
} from "../../constants/history";
import { DIMENSIONS } from "../../constants/dimensions";
import { useMessageCharacterHover } from "../../hooks/useMessageCharacterHover";
import ChatHistoryRow from "./ChatHistoryRow";
import MessageSkeleton from "./MessageSkeleton";
import { useChatRuntimeStore, selectChatRenderRows } from "./chatRuntimeStore";
import { measuredHistoryRowHeights } from "./scrollGeometry";
import { chatRuntimeController } from "./chatRuntimeController";
import { liveBubbleIntersectsViewport } from "./chatViewport";
import { useChatScrollController } from "./useChatScrollController";
import type { ChatRenderRow, HistorySkeletonRowDto } from "./types";

export interface ChatVirtualListHandle {
  returnToBottom: () => Promise<void>;
  jumpToRound: (rowIndex: number) => Promise<void>;
}

interface VirtualMessageListProps {
  archived: boolean;
  onImageClick: (src: string) => void;
  onEditMessage: (id: string, content: MessageContent) => void | Promise<void>;
  onDeleteMessages: (count: number) => void;
  onDeleteSingleMessage?: (index: number) => void;
  onRegenerateResponse: (messageIndex: number) => void;
  onDropFiles: (files: FileList) => void;
  agents?: string[];
  onToggleMessageVisibility?: (messageId: string, agentName: string) => void;
  topSafeSpacePx: number;
}

interface ChatListContext extends VirtualMessageListProps {
  skeleton: HistorySkeletonRowDto[];
  renderRows: ChatRenderRow[];
  beginUserHeightMutation: () => void;
  hasChatContent: boolean;
}

const ChatList = forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement> & { context: ChatListContext }>(
  function ChatList({ style, children, context, ...props }, ref) {
    return (
      <div {...props} ref={ref} style={style} className="chat-content">
        {context.hasChatContent && (
          <div
            className="chat-top-safe-space"
            style={{ height: context.topSafeSpacePx }}
            aria-hidden="true"
          />
        )}
        {children}
      </div>
    );
  },
);

function ChatSeekPlaceholder({ index, height, context }: { index: number; height: number; context: ChatListContext }) {
  const row = context.renderRows[index];
  const skeleton = row?.skeleton;
  const reservedHeight = Number.isFinite(height) && height >= 0 ? height : 0;
  return (
    <div
      className="chat-seek-placeholder"
      style={{ height: reservedHeight, minHeight: reservedHeight }}
      data-history-row-id={row?.historyRowId || undefined}
    >
      {skeleton && <MessageSkeleton row={skeleton} />}
    </div>
  );
}

function MeasuredChatRow({ id, historyRowId, children }: { id: string; historyRowId?: string | null; children: ReactNode }) {
  const elementRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const element = elementRef.current;
    if (!element) return;
    const report = () => useChatRuntimeStore.getState().mergeRowHeights([
      { id, height: element.getBoundingClientRect().height },
    ]);
    report();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(report);
    observer.observe(element);
    return () => observer.disconnect();
  }, [id]);
  return (
    <div ref={elementRef} className="chat-history-row chat-history-row--history" data-history-row-id={historyRowId || undefined} data-render-row-id={id} data-message-id={id}>
      {children}
    </div>
  );
}

function ChatLiveFooter({ context }: { context: ChatListContext }) {
  const footerRef = useRef<HTMLDivElement>(null);
  const liveRows = useChatRuntimeStore((state) => state.liveRows);
  const pendingStreamFinishes = useChatRuntimeStore((state) => state.pendingStreamFinishes);
  useLayoutEffect(() => {
    const footer = footerRef.current;
    if (!footer) return;
    for (const pending of Object.values(pendingStreamFinishes)) {
      const runtime = useChatRuntimeStore.getState();
      if (!runtime.pendingStreamFinishes[pending.streamId]) continue;
      const live = runtime.liveRows.find((row) => row.id === pending.streamId);
      runtime.finishStream(
        pending.streamId, pending.content, pending.metrics,
        liveBubbleIntersectsViewport(null, live?.renderId || pending.streamId), pending.finishReason,
      );
    }
  }, [pendingStreamFinishes, liveRows]);
  useLayoutEffect(() => () => {
    const runtime = useChatRuntimeStore.getState();
    for (const pending of Object.values(runtime.pendingStreamFinishes)) {
      runtime.finishStream(pending.streamId, pending.content, pending.metrics, false, pending.finishReason);
    }
  }, []);
  const processing = useChatRuntimeStore((state) => state.processing);
  const tailPageError = useChatRuntimeStore((state) =>
    Object.values(state.pageErrors).find((error) => error.endIndex >= state.knownHistoryCount));
  return (
    <div ref={footerRef} className="chat-live-footer">
      {processing && !liveRows.some((row) => row.streaming && row.message.role === "assistant") && (
        <div className="message message-assistant message-new" data-chat-scope="waiting" data-message-role="assistant">
          <div className="message-avatar waiting-avatar">⚡</div>
          <div className="message-bubble" data-chat-scope="bubble">
            <div className="typing-indicator"><span /><span /><span /></div>
          </div>
        </div>
      )}
      {tailPageError && (
        <div className="chat-history-page-error">
          <span>最新历史加载失败：{tailPageError.message}</span>
          <button type="button" onClick={() => chatRuntimeController.retryPage(tailPageError.startIndex, tailPageError.endIndex)}>重试</button>
        </div>
      )}
      {context.hasChatContent && (
        <div className="chat-bottom-safe-space" />
      )}
    </div>
  );
}

const VIRTUOSO_COMPONENTS: Components<ChatRenderRow, ChatListContext> = {
  List: ChatList,
  ScrollSeekPlaceholder: ChatSeekPlaceholder,
  Footer: ChatLiveFooter,
};

function renderChatRow(
  _index: number,
  row: ChatRenderRow,
  context: ChatListContext,
) {
  return (
    <MeasuredChatRow id={row.renderId} historyRowId={row.historyRowId}>
      <ChatHistoryRow
        row={row}
        archived={context.archived}
        onImageClick={context.onImageClick}
        onEditMessage={context.onEditMessage}
        onDeleteMessages={context.onDeleteMessages}
        onDeleteSingleMessage={context.onDeleteSingleMessage}
        onRegenerateResponse={context.onRegenerateResponse}
        agents={context.agents}
        onToggleMessageVisibility={context.onToggleMessageVisibility}
        onUserHeightMutation={context.beginUserHeightMutation}
      />
    </MeasuredChatRow>
  );
}

const VirtualMessageList = forwardRef<ChatVirtualListHandle, VirtualMessageListProps>(
  function VirtualMessageList(props, ref) {
    const runtime = useChatRuntimeStore();
    const skeleton = runtime.skeleton;
    const renderRows = useMemo(() => selectChatRenderRows(runtime), [runtime]);
    const skeletonError = useChatRuntimeStore((state) => state.skeletonError);
    const initialReady = useChatRuntimeStore((state) => state.initialReady);
    const liveVersion = useChatRuntimeStore((state) => state.liveVersion);
    const liveRows = useChatRuntimeStore((state) => state.liveRows);
    const processing = useChatRuntimeStore((state) => state.processing);
    const virtuosoRef = useRef<VirtuosoHandle>(null);
    const [scrollerElement, setScrollerElement] = useState<HTMLDivElement | null>(null);
    const hoverRootRef = useMemo(
      () => ({ current: scrollerElement }),
      [scrollerElement],
    );
    useMessageCharacterHover(hoverRootRef);
    const scroll = useChatScrollController(virtuosoRef, scrollerElement, props.topSafeSpacePx);

    useLayoutEffect(() => {
      scroll.followAfterLiveCommit();
    }, [liveVersion, processing, skeleton, liveRows, scroll.followAfterLiveCommit]);

    useImperativeHandle(ref, () => ({
      returnToBottom: scroll.returnToBottom,
      jumpToRound: scroll.jumpToRound,
    }), [
      scroll.returnToBottom,
      scroll.jumpToRound,
    ]);

    const hasChatContent = renderRows.length > 0 || processing;
    const context = useMemo<ChatListContext>(() => ({
      ...props,
      skeleton,
      renderRows,
      beginUserHeightMutation: scroll.beginUserHeightMutation,
      hasChatContent,
    }), [
      props.archived,
      props.onImageClick,
      props.onEditMessage,
      props.onDeleteMessages,
      props.onDeleteSingleMessage,
      props.onRegenerateResponse,
      props.onDropFiles,
      props.agents,
      props.onToggleMessageVisibility,
      props.topSafeSpacePx,
      skeleton,
      renderRows,
      hasChatContent,
      scroll.beginUserHeightMutation,
    ]);

    const setScrollerRef = useCallback((element: HTMLElement | Window | null) => {
      setScrollerElement(element instanceof HTMLDivElement ? element : null);
    }, []);

    const handleItemsRendered = useCallback((items: ListItem<ChatRenderRow>[]) => {
      const entries = measuredHistoryRowHeights(items);
      if (entries.length) useChatRuntimeStore.getState().mergeRowHeights(entries);
    }, []);

    if (skeletonError && skeleton.length === 0) {
      return (
        <div className="chat-history-load-error">
          <span>历史加载失败：{skeletonError}</span>
          <button
            type="button"
            onClick={() => {
              const state = useChatRuntimeStore.getState();
              void chatRuntimeController.initialize(state.sessionId, state.knownHistoryCount);
            }}
          >
            重试
          </button>
        </div>
      );
    }

    if (!initialReady && skeleton.length === 0) return null;

    return (
      <>
        <Virtuoso
          ref={virtuosoRef}
          className="chat-area"
          style={{ flex: "1 1 0", minHeight: 0 }}
          data={renderRows}
          context={context}
          computeItemKey={(_index, row) => row.renderId}
          initialTopMostItemIndex={renderRows.length ? { index: "LAST", align: "end" } : 0}
          itemContent={renderChatRow}
          itemsRendered={handleItemsRendered}
          components={VIRTUOSO_COMPONENTS}
          scrollerRef={setScrollerRef}
          rangeChanged={(range: ListRange) => scroll.handleRangeChanged(range)}
          atBottomThreshold={DIMENSIONS.SCROLL_BOTTOM_THRESHOLD}
          atBottomStateChange={scroll.handleAtBottomStateChange}
          totalListHeightChanged={scroll.handleTotalListHeightChanged}
          scrollSeekConfiguration={{
            enter: (velocity) => Math.abs(velocity) > HISTORY_SCROLL_SEEK_ENTER,
            exit: (velocity) => Math.abs(velocity) < HISTORY_SCROLL_SEEK_EXIT,
          }}
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            if (event.dataTransfer.files.length) props.onDropFiles(event.dataTransfer.files);
          }}
        />
      </>
    );
  },
);

export default VirtualMessageList;
