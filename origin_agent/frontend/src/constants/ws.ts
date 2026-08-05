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
  PONG:              "pong",
} as const;

/** WebSocket 传出消息类型 */
export const WS_OUT = {
  USER_MESSAGE:   "user_message",
  HANDSFREE_MODE: "handsfree_mode",
  PING:           "ping",
  FILE_UPLOAD:    "file_upload",
} as const;