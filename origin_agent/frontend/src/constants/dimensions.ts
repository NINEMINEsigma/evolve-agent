/** 尺寸/断点常量 */
export const DIMENSIONS = {
  SIDEBAR_DEFAULT:        320,   // 侧边栏默认宽度
  SIDEBAR_MIN:            200,   // 侧边栏最小宽度
  SIDEBAR_MAX:            560,   // 侧边栏最大宽度
  TAB_RAIL_WIDTH:         44,    // 右侧 Tab 栏立柱宽度 (px)
  TAB_RAIL_WIDTH_MOBILE:  40,    // 右侧 Tab 栏立柱移动端宽度 (px)
  INPUT_MAX_SCROLL:       200,   // 输入框最大滚动高度
  MENU_MAX_HEIGHT:        244,   // 提及菜单最大高度
  MOBILE_BREAKPOINT:      768,   // 移动端断点 (px)
  MINIMAP_MIN_HEIGHT:     24,    // 小地图最小元素高度
  TREE_INDENT:            16,    // 文件树缩进步长
  AGENTSPACE_SIDEBAR_DEFAULT: 280, // Agentspace 文件树默认宽度
  AGENTSPACE_SIDEBAR_MIN: 190,     // Agentspace 文件树最小宽度
  AGENTSPACE_SIDEBAR_MAX: 640,     // Agentspace 文件树最大宽度
  SCROLL_BOTTOM_THRESHOLD: 20,   // 滚动到底部阈值
  LONG_MESSAGE_CHARS:     1200,  // 长消息字符阈值
  LONG_MESSAGE_LINES:     18,    // 长消息行数阈值
  MAX_PASTE_IMAGE_SIZE:   20 * 1024 * 1024, // 20MB
  MAX_PASTE_AUDIO_SIZE:   25 * 1024 * 1024, // 25MB
  MAX_PASTE_VIDEO_SIZE:   50 * 1024 * 1024, // 50MB
  INPUT_ACTIONS_COLLAPSE_RATIO: 0.4, // 输入栏左下功能组宽度超过视口宽度该比例时收起为菜单按钮
  INPUT_ACTION_BTN_WIDTH: 36,       // 输入栏功能按钮展开态固有宽度 (px)，等于 --icon-btn-md，用于静态宽度估算
} as const;