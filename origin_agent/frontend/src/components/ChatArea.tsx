import { useMemo, useRef, useState } from "react";
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
}

export default function ChatArea({ messages, waiting, archived, onImageClick, onToggleCollapse, onEditMessage, onDeleteMessages, onRegenerateResponse, bottomRef, onDropFiles, streamingMessage, chatAreaRef: externalChatAreaRef }: ChatAreaProps) {
  const [dragOver, setDragOver] = useState(false);
  const internalChatAreaRef = useRef<HTMLDivElement>(null);
  const chatAreaRef = externalChatAreaRef || internalChatAreaRef;
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
      <Minimap messages={messages} chatAreaRef={chatAreaRef} />
    </div>
  );
}