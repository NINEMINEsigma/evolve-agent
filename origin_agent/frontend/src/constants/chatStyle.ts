/**
 * 聊天区自定义样式常量 — 公开选择器契约与限制。
 *
 * 这些常量供 useSessionChatStyle hook、ChatStyleLayer 组件和提示词模板共用。
 * data-chat-scope 属性构成稳定公开样式契约，向 Evolve Agent 承诺长期兼容。
 */

/** 聊天区自定义样式核心常量 */
export const CHAT_STYLE = {
  /** CSS 文件最大字节数（256 KiB） */
  MAX_BYTES: 256 * 1024,

  /** 远程字体加载超时毫秒 */
  FONT_TIMEOUT_MS: 5000,

  /** 聊天区作用域根选择器（公开契约） */
  SCOPE_SELECTOR: ".chat-area",

  /** 自定义 @font-face 的 font-family 前缀要求 */
  FONT_FAMILY_PREFIX: "ChatStyle-",

  /**
   * 构建会话级聊天区 CSS 的前端访问 URL。
   * sessionId 为空时返回 null。
   */
  INDEX_URL: (sessionId: string): string | null => {
    if (!sessionId) return null;
    const encoded = encodeURIComponent(sessionId);
    return `/files/ws/sessions/${encoded}/chat-style/index.css`;
  },
} as const;

/**
 * 公开样式选择器契约 — 在提示词模板和前端文档中向 Evolve Agent 说明。
 * 优先使用 data-chat-scope / data-message-role 属性选择器；
 * 内部类名不保证跨版本兼容。
 */
export const CHAT_STYLE_SELECTORS = {
  // 作用域根
  scope: ".chat-area",

  // 消息根
  message: '[data-chat-scope="message"]',
  messageRole: (role: string) => `[data-message-role="${role}"]`,
  userMessage: '.chat-area [data-message-role="user"]',
  assistantMessage: '.chat-area [data-message-role="assistant"]',
  toolMessage: '.chat-area [data-message-role="tool"]',

  // 交互状态
  hovered: ".chat-area [data-chat-scope=\"message\"]:hover",
  characterHovered: '.chat-area [data-character-hovered="true"]',

  // 消息内部区域
  bubble: '[data-chat-scope="bubble"]',
  content: '[data-chat-scope="content"]',
  reasoning: '[data-chat-scope="reasoning"]',
  toolCall: '[data-chat-scope="tool-call"]',
  toolDetail: '[data-chat-scope="tool-detail"]',
  code: '[data-chat-scope="code"]',
  attachments: '[data-chat-scope="attachments"]',
  toolbar: '[data-chat-scope="toolbar"]',
  meta: '[data-chat-scope="meta"]',
  waiting: '[data-chat-scope="waiting"]',
} as const;
