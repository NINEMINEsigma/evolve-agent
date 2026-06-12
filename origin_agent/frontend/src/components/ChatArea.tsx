import { useMemo } from "react";
import { ChatMessage } from "../types";
import MessageItem from "./MessageItem";

interface ChatAreaProps {
  messages: ChatMessage[];
  waiting: boolean;
  onImageClick: (src: string) => void;
  bottomRef: React.RefObject<HTMLDivElement>;
}

export default function ChatArea({ messages, waiting, onImageClick, bottomRef }: ChatAreaProps) {
  const messageList = useMemo(() =>
    messages.map((m) => (
      <MessageItem key={m.id} message={m} onImageClick={onImageClick} />
    )),
    [messages, onImageClick]
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