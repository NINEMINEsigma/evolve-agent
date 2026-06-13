import { useMemo } from "react";
import { ChatMessage } from "../types";
import MessageItem from "./MessageItem";

interface ChatAreaProps {
  messages: ChatMessage[];
  waiting: boolean;
  archived: boolean;
  onImageClick: (src: string) => void;
  onToggleCollapse: (id: string) => void;
  onEditMessage: (id: string, content: string) => void | Promise<void>;
  bottomRef: React.RefObject<HTMLDivElement>;
}

export default function ChatArea({ messages, waiting, archived, onImageClick, onToggleCollapse, onEditMessage, bottomRef }: ChatAreaProps) {
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
    <main className="chat-area">
      {messageList}

      {waiting && (
        <div className="message message-agent">
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
  );
}