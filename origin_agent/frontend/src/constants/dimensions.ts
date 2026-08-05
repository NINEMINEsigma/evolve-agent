/** 尺寸/断点常量 */
export const DIMENSIONS = {
  SUBAGENT_PANEL_DEFAULT: 420,   // 子代理面板默认宽度
  SUBAGENT_PANEL_MIN:     280,   // 子代理面板最小宽度
  SUBAGENT_PANEL_MAX:     800,   // 子代理面板最大宽度
  INPUT_MAX_SCROLL:       200,   // 输入框最大滚动高度
  MENU_MAX_HEIGHT:        244,   // 提及菜单最大高度
  MOBILE_BREAKPOINT:      768,   // 移动端断点 (px)
  MINIMAP_MIN_HEIGHT:     24,    // 小地图最小元素高度
  TREE_INDENT:            16,    // 文件树缩进步长
  SCROLL_BOTTOM_THRESHOLD: 20,   // 滚动到底部阈值
  LONG_MESSAGE_CHARS:     1200,  // 长消息字符阈值
  LONG_MESSAGE_LINES:     18,    // 长消息行数阈值
  MAX_PASTE_IMAGE_SIZE:   20 * 1024 * 1024, // 20MB
} as const;