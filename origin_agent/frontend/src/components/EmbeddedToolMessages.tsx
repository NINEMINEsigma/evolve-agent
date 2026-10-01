import type { ChatMessage, EmbeddedToolMessage } from "../types";
import MessageBody from "./MessageBody";
import { useChatRuntimeStore } from "../features/chat/chatRuntimeStore";
import { isMessageVisible } from "../features/chat/messageVisibility";

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
  const showSystemUserMessages = useChatRuntimeStore((state) => state.showSystemUserMessages);
  const visibleMessages = messages
    .map((message, index) => ({ message, index }))
    .filter(({ message }) => isMessageVisible(message.role, message.character_name, showSystemUserMessages));
  if (visibleMessages.length === 0) return null;
  return (
    <div className="tool-embedded-messages" data-chat-scope="embedded-messages">
      <div className="tool-embedded-messages-title">工具执行期间收到的消息</div>
      {visibleMessages.map(({ message: embedded, index }) => {
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
