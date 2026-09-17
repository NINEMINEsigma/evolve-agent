import type { MessageContent } from "../../types";
import MessageItem from "../../components/MessageItem";
import MessageSkeleton from "./MessageSkeleton";
import { chatRuntimeController } from "./chatRuntimeController";
import { useChatRuntimeStore } from "./chatRuntimeStore";
import type { HistorySkeletonRowDto } from "./types";

interface ChatHistoryRowProps {
  row: HistorySkeletonRowDto;
  archived: boolean;
  onImageClick: (src: string) => void;
  onEditMessage: (id: string, content: MessageContent) => void | Promise<void>;
  onDeleteMessages: (count: number) => void;
  onDeleteSingleMessage?: (index: number) => void;
  onRegenerateResponse: (messageIndex: number) => void;
  agents?: string[];
  onToggleMessageVisibility?: (messageId: string, agentName: string) => void;
  onUserHeightMutation: () => void;
}

export default function ChatHistoryRow({
  row,
  archived,
  onImageClick,
  onEditMessage,
  onDeleteMessages,
  onDeleteSingleMessage,
  onRegenerateResponse,
  agents,
  onToggleMessageVisibility,
  onUserHeightMutation,
}: ChatHistoryRowProps) {
  const message = useChatRuntimeStore((state) => state.contentByRowId[row.row_id]);
  const processing = useChatRuntimeStore((state) => state.processing);
  const lastUserIndex = useChatRuntimeStore((state) => state.lastUserHistoryIndex);
  const pageError = useChatRuntimeStore((state) =>
    Object.values(state.pageErrors).find((error) =>
      row.history_index >= error.startIndex && row.history_index < error.endIndex));

  if (!message) {
    if (pageError && row.history_index === pageError.startIndex) {
      return (
        <div className="chat-history-page-error" data-history-row-id={row.row_id}>
          <span>历史内容加载失败：{pageError.message}</span>
          {pageError.retryable && (
            <button
              type="button"
              onClick={() => chatRuntimeController.retryPage(pageError.startIndex, pageError.endIndex)}
            >
              重试
            </button>
          )}
        </div>
      );
    }
    return <MessageSkeleton row={row} />;
  }

  return (
    <MessageItem
      message={message}
      archived={archived || processing}
      onImageClick={onImageClick}
      onToggleCollapse={(id) => {
        onUserHeightMutation();
        useChatRuntimeStore.setState((state) => ({
          contentByRowId: {
            ...state.contentByRowId,
            [id]: {
              ...state.contentByRowId[id],
              collapsed: state.contentByRowId[id]?.collapsed === undefined
                ? false
                : !state.contentByRowId[id]?.collapsed,
            },
          },
        }));
      }}
      onEditMessage={onEditMessage}
      onDeleteMessages={onDeleteMessages}
      onDeleteSingleMessage={onDeleteSingleMessage}
      onRegenerateResponse={onRegenerateResponse}
      isLastUserMessage={message.role === "user" && row.history_index === lastUserIndex}
      isAfterLastUser={row.history_index > lastUserIndex}
      waiting={processing}
      agents={agents}
      onToggleMessageVisibility={onToggleMessageVisibility}
      onUserHeightMutation={onUserHeightMutation}
    />
  );
}
