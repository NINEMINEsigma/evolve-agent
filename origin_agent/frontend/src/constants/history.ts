// Chat history paging and virtualization constants.
export const HISTORY_PAGE_SIZE = 80;
export const HISTORY_PAGE_OVERSCAN_ROWS = 20;
export const HISTORY_NEAR_BOTTOM_ROWS = 8;
// 主聊天用户滚动意图的有效时间，单位：毫秒；连续输入会刷新窗口。
export const CHAT_SCROLL_USER_INTENT_MS = 700;
export const HISTORY_SCROLL_SEEK_ENTER = 1200;
export const HISTORY_SCROLL_SEEK_EXIT = 160;
// 骨架估算行距（px）— 与 chat.css 消息行距保持同步的估算口径
export const HISTORY_ROW_GAP_PX = 6;
// 聊天列表底部留白（px）— 与 chat.css 底部安全区保持同步
export const CHAT_BOTTOM_SAFE_SPACE_PX = 120;
// 滚动物理指标与行高测量的比较精度（px）
export const CHAT_MEASUREMENT_EPSILON_PX = 0.5;

export const HISTORY_SKELETON_HEIGHTS = {
  user: 72,
  assistant: 104,
  tool: 48,
  system: 44,
} as const;
