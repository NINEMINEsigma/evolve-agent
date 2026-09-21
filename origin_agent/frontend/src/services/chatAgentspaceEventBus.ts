import type { AgentspaceEvent } from "../types";

export type ChatAgentspaceEventListener = (event: AgentspaceEvent) => void;

const listeners = new Set<ChatAgentspaceEventListener>();

/** 订阅聊天页已有 WebSocket 转发的 Agentspace 事件。 */
export function subscribeChatAgentspaceEvents(
  listener: ChatAgentspaceEventListener,
): () => void {
  listeners.add(listener);
  let subscribed = true;
  return () => {
    if (!subscribed) return;
    subscribed = false;
    listeners.delete(listener);
  };
}

/** 向当前聊天页的视觉功能扇出单个 Agentspace 事件。 */
export function publishChatAgentspaceEvent(event: AgentspaceEvent): void {
  for (const listener of Array.from(listeners)) {
    try {
      listener(event);
    } catch (error) {
      console.error("Chat Agentspace event listener failed", error);
    }
  }
}

/** 仅供单元测试隔离模块级订阅者。 */
export function resetChatAgentspaceEventBusForTest(): void {
  listeners.clear();
}
