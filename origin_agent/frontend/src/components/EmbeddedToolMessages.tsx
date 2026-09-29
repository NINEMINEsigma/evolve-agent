import type { ChatMessage, EmbeddedToolMessage } from "../types";
import MessageBody from "./MessageBody";

interface EmbeddedToolMessagesProps {
  messages: EmbeddedToolMessage[];
  onImageClick: (src: string) => void;
  onUserHeightMutation?: () => void;
}

export default function EmbeddedToolMessages({
  messages,
  onImageClick,
  onUserHeightMutation,
}: EmbeddedToolMessagesProps) {
  if (messages.length === 0) return null;
  return (
    <div className="tool-embedded-messages" data-chat-scope="embedded-messages">
      <div className="tool-embedded-messages-title">工具执行期间收到的消息</div>
      {messages.map((embedded, index) => {
        const message: ChatMessage = {
          id: `embedded-tool-message-${index}`,
          role: "user",
          content: embedded.content,
          characterName: embedded.character_name,
        };
        return (
          <article className="tool-embedded-message" key={message.id}>
            <div className="tool-embedded-message-meta">
              {embedded.character_name || "用户"}
              {embedded.source ? ` · ${embedded.source}` : ""}
              {embedded.timestamp ? ` · ${embedded.timestamp}` : ""}
            </div>
            <MessageBody
              message={message}
              onImageClick={onImageClick}
              onUserHeightMutation={onUserHeightMutation}
            />
          </article>
        );
      })}
    </div>
  );
}
