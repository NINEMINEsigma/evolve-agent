// Chat history paging and virtualization constants.
export const HISTORY_PAGE_SIZE = 80;
export const HISTORY_PAGE_OVERSCAN_ROWS = 20;
export const HISTORY_NEAR_BOTTOM_ROWS = 8;
export const HISTORY_SCROLL_SEEK_ENTER = 1200;
export const HISTORY_SCROLL_SEEK_EXIT = 160;
export const HISTORY_ROW_GAP_PX = 6;
export const CHAT_BOTTOM_SAFE_SPACE_PX = 120;
export const MINIMAP_THUMB_MIN_HIT_PX = 16;
export const MINIMAP_MEASUREMENT_EPSILON_PX = 0.5;

export const HISTORY_SKELETON_HEIGHTS = {
  user: 72,
  assistant: 104,
  tool: 48,
  system: 44,
} as const;
