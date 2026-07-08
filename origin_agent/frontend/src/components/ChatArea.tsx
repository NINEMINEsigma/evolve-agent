import { useEffect, useMemo, useRef, useState } from "react";
import { ChatMessage } from "../types";
import MessageItem from "./MessageItem";
import Minimap from "./Minimap";

interface ChatAreaProps {
  messages: ChatMessage[];
  waiting: boolean;
  archived: boolean;
  onImageClick: (src: string) => void;
  onToggleCollapse: (id: string) => void;
  onEditMessage: (id: string, content: string) => void | Promise<void>;
  onDeleteMessages: (count: number) => void;
  onRegenerateResponse: () => void;
  bottomRef: React.RefObject<HTMLDivElement>;
  onDropFiles: (files: FileList) => void;
  streamingMessage?: ChatMessage | null;
  chatAreaRef?: React.RefObject<HTMLDivElement>;
  agents?: string[];
  onToggleMessageVisibility?: (messageId: string, agentName: string) => void;
  onScrollToBottom?: () => void;
}

export default function ChatArea({ messages, waiting, archived, onImageClick, onToggleCollapse, onEditMessage, onDeleteMessages, onRegenerateResponse, bottomRef, onDropFiles, streamingMessage, chatAreaRef: externalChatAreaRef, agents, onToggleMessageVisibility, onScrollToBottom }: ChatAreaProps) {
  const [dragOver, setDragOver] = useState(false);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const internalChatAreaRef = useRef<HTMLDivElement>(null);
  const chatAreaRef = externalChatAreaRef || internalChatAreaRef;

  useEffect(() => {
    const chat = chatAreaRef.current;
    if (!chat) return;
    const onScroll = () => {
      const isAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight <= 20;
      setShowScrollButton(!isAtBottom);
    };
    chat.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => chat.removeEventListener("scroll", onScroll);
  }, [chatAreaRef]);

  const lastUserMsgId = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "user") return messages[i].id;
    }
    return null;
  }, [messages]);
  const messageList = useMemo(() =>
    messages.map((m) => (
      <MessageItem
        key={m.id}
        message={m}
        archived={archived}
        onImageClick={onImageClick}
        onToggleCollapse={onToggleCollapse}
        onEditMessage={onEditMessage}
        onDeleteMessages={onDeleteMessages}
        onRegenerateResponse={onRegenerateResponse}
        isLastUserMessage={m.id === lastUserMsgId}
        agents={agents}
        onToggleMessageVisibility={onToggleMessageVisibility}
      />
    )),
    [messages, archived, onImageClick, onToggleCollapse, onEditMessage, onDeleteMessages, onRegenerateResponse, lastUserMsgId]
  );

  return (
    <div className="chat-area-wrapper">
      <main
        ref={chatAreaRef}
        className={`chat-area ${dragOver ? "chat-area-drag-over" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            onDropFiles(e.dataTransfer.files);
          }
        }}
      >
        {messageList}

        {streamingMessage && (
          <MessageItem
            message={streamingMessage}
            archived={archived}
            onImageClick={onImageClick}
            onToggleCollapse={onToggleCollapse}
            onEditMessage={onEditMessage}
            onDeleteMessages={onDeleteMessages}
            onRegenerateResponse={onRegenerateResponse}
            streaming
          />
        )}

        {waiting && !streamingMessage && (
          <div className="message message-assistant" data-message-id="__waiting__">
            <div className="message-avatar waiting-avatar">⚡</div>
            <div className="message-bubble">
              <div className="typing-indicator">
                <span /><span /><span />
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </main>
      {onScrollToBottom && showScrollButton && (
        <button
          type="button"
          className="scroll-to-bottom"
          onClick={onScrollToBottom}
          aria-label="回到最新位置"
          title="回到最新位置"
        >
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </button>
      )}
      <Minimap messages={messages} chatAreaRef={chatAreaRef} />
    </div>
  );
}