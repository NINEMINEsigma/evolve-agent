// Chat history paging and virtualization constants.
export const HISTORY_PAGE_SIZE = 80;
export const HISTORY_PAGE_OVERSCAN_ROWS = 20;
export const HISTORY_NEAR_BOTTOM_ROWS = 8;
// 主聊天用户滚动意图的有效时间，单位：毫秒；连续输入会刷新窗口。
export const CHAT_SCROLL_USER_INTENT_MS = 700;
export const HISTORY_SCROLL_SEEK_ENTER = 1200;
export const HISTORY_SCROLL_SEEK_EXIT = 160;
export const HISTORY_ROW_GAP_PX = 6;
// 与 variables.css 的 --header-height: 56px 保持同步；桌面端顶部覆盖层的聊天安全区
export const CHAT_TOP_SAFE_SPACE_PX = 56;
export const CHAT_BOTTOM_SAFE_SPACE_PX = 120;
export const MINIMAP_THUMB_MIN_HIT_PX = 16;
export const MINIMAP_MEASUREMENT_EPSILON_PX = 0.5;

export const HISTORY_SKELETON_HEIGHTS = {
  user: 72,
  assistant: 104,
  tool: 48,
  system: 44,
} as const;
