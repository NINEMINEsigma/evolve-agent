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
import MessageItem from "../../components/MessageItem";
import {
  HISTORY_SCROLL_SEEK_ENTER,
  HISTORY_SCROLL_SEEK_EXIT,
} from "../../constants/history";
import { useMessageCharacterHover } from "../../hooks/useMessageCharacterHover";
import ChatHistoryRow from "./ChatHistoryRow";
import MessageSkeleton from "./MessageSkeleton";
import { useChatRuntimeStore } from "./chatRuntimeStore";
import { measuredHistoryRowHeights } from "./minimapGeometry";
import { chatRuntimeController } from "./chatRuntimeController";
import { liveBubbleIntersectsViewport } from "./chatViewport";
import { useChatScrollController } from "./useChatScrollController";
import type { HistorySkeletonRowDto } from "./types";

export interface ChatVirtualListHandle {
  returnToBottom: () => Promise<void>;
  beginMinimapDrag: () => void;
  previewMinimapScrollTop: (scrollTop: number) => void;
  commitMinimapDrag: (scrollTop: number) => Promise<void>;
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

function ChatSeekPlaceholder({ index, context }: { index: number; context: ChatListContext }) {
  const row = context.skeleton[index];
  return row ? <MessageSkeleton row={row} /> : null;
}

function MeasuredLiveRow({ id, children }: { id: string; children: ReactNode }) {
  const elementRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const element = elementRef.current;
    if (!element) return;
    const report = () => {
      useChatRuntimeStore.getState().mergeRowHeights([
        { id, height: element.getBoundingClientRect().height },
      ]);
    };
    report();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(report);
    observer.observe(element);
    return () => observer.disconnect();
  }, [id]);
  return (
    <div ref={elementRef} className="chat-history-row" data-history-row-id={id}>
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
      runtime.finishStream(
        pending.streamId, pending.content, pending.metrics,
        liveBubbleIntersectsViewport(footer, pending.streamId), pending.finishReason,
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
      {liveRows.map((row) => (
        <MeasuredLiveRow key={row.id} id={row.id}>
          <MessageItem
            message={row.message}
            archived={context.archived || processing}
            onImageClick={context.onImageClick}
            onToggleCollapse={(id) => useChatRuntimeStore.getState().toggleMessageCollapse(id, "live")}
            onEditMessage={context.onEditMessage}
            onDeleteMessages={context.onDeleteMessages}
            onDeleteSingleMessage={context.onDeleteSingleMessage}
            onRegenerateResponse={context.onRegenerateResponse}
            waiting={processing}
            streaming={row.streaming}
            onUserHeightMutation={context.beginUserHeightMutation}
            animateEntry
          />
        </MeasuredLiveRow>
      ))}
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
      {(context.skeleton.length > 0 || liveRows.length > 0 || processing) && (
        <div className="chat-bottom-safe-space" />
      )}
    </div>
  );
}

const VIRTUOSO_COMPONENTS: Components<HistorySkeletonRowDto, ChatListContext> = {
  List: ChatList,
  ScrollSeekPlaceholder: ChatSeekPlaceholder,
  Footer: ChatLiveFooter,
};

function renderHistoryRow(
  _index: number,
  row: HistorySkeletonRowDto,
  context: ChatListContext,
) {
  return (
    <div className="chat-history-row chat-history-row--history" data-history-row-id={row.row_id}>
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
    </div>
  );
}

const VirtualMessageList = forwardRef<ChatVirtualListHandle, VirtualMessageListProps>(
  function VirtualMessageList(props, ref) {
    const skeleton = useChatRuntimeStore((state) => state.skeleton);
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
    }, [liveVersion, processing, scroll.followAfterLiveCommit]);

    useImperativeHandle(ref, () => ({
      returnToBottom: scroll.returnToBottom,
      beginMinimapDrag: scroll.beginMinimapDrag,
      previewMinimapScrollTop: scroll.previewMinimapScrollTop,
      commitMinimapDrag: scroll.commitMinimapDrag,
    }), [
      scroll.returnToBottom,
      scroll.beginMinimapDrag,
      scroll.previewMinimapScrollTop,
      scroll.commitMinimapDrag,
    ]);

    const hasChatContent = skeleton.length > 0 || liveRows.length > 0 || processing;
    const context = useMemo<ChatListContext>(() => ({
      ...props,
      skeleton,
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
      hasChatContent,
      scroll.beginUserHeightMutation,
    ]);

    const setScrollerRef = useCallback((element: HTMLElement | Window | null) => {
      setScrollerElement(element instanceof HTMLDivElement ? element : null);
    }, []);

    const handleItemsRendered = useCallback((items: ListItem<HistorySkeletonRowDto>[]) => {
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
          data={skeleton}
          context={context}
          computeItemKey={(_index, row) => row.row_id}
          initialTopMostItemIndex={skeleton.length ? { index: "LAST", align: "end" } : 0}
          itemContent={renderHistoryRow}
          itemsRendered={handleItemsRendered}
          components={VIRTUOSO_COMPONENTS}
          scrollerRef={setScrollerRef}
          rangeChanged={(range: ListRange) => scroll.handleRangeChanged(range)}
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
