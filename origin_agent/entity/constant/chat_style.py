"""会话聊天区自定义样式和本地字体常量。"""

# ============================================================================
# 会话聊天区自定义样式 (Session Chat Style)
# ============================================================================

# 会话级聊天区 CSS 目录名 — 位于 ws:sessions/<session_id>/ 下
CHAT_STYLE_DIR_NAME: str = "chat-style"

# 聊天区自定义样式的固定入口文件名
CHAT_STYLE_ENTRY_FILE: str = "index.css"

# 聊天区 CSS 文件最大字节数（256 KiB）— 超限时按资源级失败处理，整份不生效
CHAT_STYLE_MAX_BYTES: int = 256 * 1024

# 本地字体文件 HTTP 路由前缀 — 前端通过此 URL 访问操作系统绝对路径字体
# 不经过沙盒命名空间，直接读取文件系统路径
LOCAL_FONT_HTTP_PREFIX: str = "/local-font"

# 单个本地字体文件最大字节数（20 MiB）
LOCAL_FONT_MAX_BYTES: int = 20 * 1024 * 1024

# 本地字体允许的文件扩展名（白名单）
LOCAL_FONT_ALLOWED_EXTENSIONS: tuple[str, ...] = (".woff2", ".woff", ".ttf", ".otf")

# 本地字体扩展名 → MIME 类型映射
LOCAL_FONT_MIME_TYPES: dict[str, str] = {
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
}

# 远程字体加载超时秒数 — 超时后使用后备字体，其他气泡样式继续生效
REMOTE_FONT_TIMEOUT_SECONDS: float = 5.0

# 自定义 @font-face 的 font-family 前缀要求 — 避免与项目默认字体同名冲突
CHAT_STYLE_FONT_FAMILY_PREFIX: str = "ChatStyle-"
