/** WebSocket 传入消息类型 */
export const WS_IN = {
  SYSTEM:            "system",
  USER_MESSAGE:      "user_message",
  ASSISTANT_MESSAGE: "assistant_message",
  TOOL_CALL:         "tool_call",
  TOOL_RESULT:       "tool_result",
  TASK_PROGRESS:     "task_progress",
  CLIPBOARD_DISPLAY: "clipboard_display",
  CONFIRM_REQUEST:   "confirm_request",
  ASK_REQUEST:       "ask_request",
  STREAM_DELTA:      "stream_delta",
  STREAM_DONE:       "stream_done",
  ERROR:             "error",
  SUBAGENT_UPDATE:   "subagent_update",
  HISTORY_SYNC:      "history_sync",
  LLM_PROFILE_CHANGED: "llm_profile_changed",
  APPROVAL_PROFILE_CHANGED: "approval_profile_changed",
  METADATA_PROFILE_CHANGED: "metadata_profile_changed",
  MODALITY_PROFILE_CHANGED: "modality_profile_changed",
  AGENTSPACE_EVENT: "agentspace_event",
  HANDSFREE_MODE:    "handsfree_mode",
  PONG:              "pong",
} as const;

/** 会话永久删除关闭码；必须与后端 WEBSOCKET_CLOSE_SESSION_DELETED 保持一致。 */
export const WS_CLOSE_SESSION_DELETED = 4004;

/** 兼容 gateway/server.py 握手欢迎文本；只用于识别连接通知，不进入聊天消息。 */
export const WS_CONNECTION_WELCOME_TEXT = "Connected to Evolve Agent";

/** WebSocket 传出消息类型 */
export const WS_OUT = {
  USER_MESSAGE:   "user_message",
  HANDSFREE_MODE: "handsfree_mode",
  PING:           "ping",
  FILE_UPLOAD:    "file_upload",
  CLIENT_DIAGNOSTIC: "client_diagnostic",
} as const;