import type { MessageContent } from "../../types";
import MessageItem from "../../components/MessageItem";
import MessageSkeleton from "./MessageSkeleton";
import { chatRuntimeController } from "./chatRuntimeController";
import { useChatRuntimeStore } from "./chatRuntimeStore";
import type { ChatRenderRow } from "./types";

interface ChatHistoryRowProps {
  row: ChatRenderRow;
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
  const processing = useChatRuntimeStore((state) => state.processing);
  const lastUserIndex = useChatRuntimeStore((state) => state.lastUserHistoryIndex);

  if (row.pageError && !row.message && row.skeleton) {
    return (
      <div className="chat-history-page-error" data-history-row-id={row.historyRowId || undefined}>
        <span>历史内容加载失败：{row.pageError.message}</span>
        {row.pageError.retryable && (
          <button
            type="button"
            onClick={() => chatRuntimeController.retryPage(row.pageError!.startIndex, row.pageError!.endIndex)}
          >
            重试
          </button>
        )}
      </div>
    );
  }

  if (!row.message) return row.skeleton ? <MessageSkeleton row={row.skeleton} /> : null;

  return (
    <MessageItem
      message={row.message}
      archived={archived || processing}
      onImageClick={onImageClick}
      onToggleCollapse={() => useChatRuntimeStore.getState().toggleMessageCollapse(row.renderId)}
      onEditMessage={onEditMessage}
      onDeleteMessages={onDeleteMessages}
      onDeleteSingleMessage={onDeleteSingleMessage}
      onRegenerateResponse={onRegenerateResponse}
      isLastUserMessage={row.message.role === "user" && row.historyIndex === lastUserIndex}
      isAfterLastUser={row.historyIndex !== null && row.historyIndex > lastUserIndex}
      waiting={processing}
      streaming={row.streaming}
      agents={agents}
      onToggleMessageVisibility={onToggleMessageVisibility}
      onUserHeightMutation={onUserHeightMutation}
    />
  );
}
