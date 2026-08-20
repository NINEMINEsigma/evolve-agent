/** 尺寸/断点常量 */
export const DIMENSIONS = {
  SUBAGENT_PANEL_DEFAULT: 520,   // 子代理面板默认宽度
  SUBAGENT_PANEL_MIN:     280,   // 子代理面板最小宽度
  SUBAGENT_PANEL_MAX:     900,   // 子代理面板最大宽度
  SIDEBAR_DEFAULT:        320,   // 侧边栏默认宽度
  SIDEBAR_MIN:            200,   // 侧边栏最小宽度
  SIDEBAR_MAX:            560,   // 侧边栏最大宽度
  DRAWER_DEFAULT:         520,   // 右侧抽屉默认宽度
  DRAWER_MIN:             320,   // 右侧抽屉最小宽度
  DRAWER_MAX:             900,   // 右侧抽屉最大宽度
  LLM_DRAWER_DEFAULT:     760,   // 模型配置抽屉默认宽度
  LLM_DRAWER_MIN:         480,   // 模型配置抽屉最小宽度
  LLM_DRAWER_MAX:         1100,  // 模型配置抽屉最大宽度
  INPUT_MAX_SCROLL:       200,   // 输入框最大滚动高度
  MENU_MAX_HEIGHT:        244,   // 提及菜单最大高度
  MOBILE_BREAKPOINT:      768,   // 移动端断点 (px)
  MINIMAP_MIN_HEIGHT:     24,    // 小地图最小元素高度
  TREE_INDENT:            16,    // 文件树缩进步长
  SCROLL_BOTTOM_THRESHOLD: 20,   // 滚动到底部阈值
  LONG_MESSAGE_CHARS:     1200,  // 长消息字符阈值
  LONG_MESSAGE_LINES:     18,    // 长消息行数阈值
  MAX_PASTE_IMAGE_SIZE:   20 * 1024 * 1024, // 20MB
  MAX_PASTE_AUDIO_SIZE:   25 * 1024 * 1024, // 25MB
} as const;