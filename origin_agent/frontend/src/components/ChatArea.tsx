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
  bottomRef: React.RefObject<HTMLDivElement>;
  onDropFiles: (files: FileList) => void;
  streamingMessage?: ChatMessage | null;
}

export default function ChatArea({ messages, waiting, archived, onImageClick, onToggleCollapse, onEditMessage, bottomRef, onDropFiles, streamingMessage }: ChatAreaProps) {
  const [dragOver, setDragOver] = useState(false);
  const chatAreaRef = useRef<HTMLDivElement>(null);
  const messageList = useMemo(() =>
    messages.map((m) => (
      <MessageItem
        key={m.id}
        message={m}
        archived={archived}
        onImageClick={onImageClick}
        onToggleCollapse={onToggleCollapse}
        onEditMessage={onEditMessage}
      />
    )),
    [messages, archived, onImageClick, onToggleCollapse, onEditMessage]
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
            streaming
          />
        )}

        {waiting && !streamingMessage && (
          <div className="message message-agent" data-message-id="__waiting__">
            <div className="message-avatar">⚡</div>
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