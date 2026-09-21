import type { AgentspaceEvent, ClientDiagnostic, WSMessage } from "../types";
import { WS_IN, WS_OUT } from "../constants/ws";

/** 聊天入口的非历史消息分流，不创建第二条网络连接。 */
export function routeChatTransportMessage(
  message: WSMessage,
  currentSessionId: string,
  publishEvent: (event: AgentspaceEvent) => void,
): boolean {
  if (message.type !== WS_IN.AGENTSPACE_EVENT) return false;
  const event = message.agentspace_event;
  if (event && (!message.session_id || !currentSessionId || message.session_id === currentSessionId)) {
    publishEvent(event);
  }
  return true;
}

/** 只生成脱敏的客户端诊断上行帧，不写入聊天消息状态。 */
export function clientDiagnosticFrame(
  sessionId: string,
  diagnostic: ClientDiagnostic,
): WSMessage {
  return {
    type: WS_OUT.CLIENT_DIAGNOSTIC,
    session_id: sessionId,
    client_diagnostic: diagnostic,
  };
}
