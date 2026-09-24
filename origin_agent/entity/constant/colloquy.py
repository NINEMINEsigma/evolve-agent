"""随意聊聊会话和历史压缩限制常量。"""

# ============================================================================
# Colloquy Loop (随意聊聊)
# ============================================================================

# 随意聊聊会话的固定 session ID
COLLOQUY_SESSION_ID: str = "____buildin_colloquy__"

# 滑动窗口压缩比例：将最早 N% 的消息压缩为一条摘要
COLLOQUY_COMPRESS_RATIO: float = 0.3

# 工具集白名单 — colloquy loop 仅允许这些 toolset 的工具。
# sandbox 管理工具集有意排除：随意聊聊会话可使用已有动态空间，但不可修改全局配置。
COLLOQUY_TOOLSET_WHITELIST: frozenset[str] = frozenset({
    "filesystem", "core", "progress", "lsp", "frontend", "code",
    "clipboard", "shell",
    "extools", "cron", "dynamic", "archive",
})

# 压缩工具默认保留最近轮次数
COMPRESS_HISTORY_DEFAULT_KEEP_ROUNDS: int = 3

# 压缩工具保留轮次的最小值
COMPRESS_HISTORY_MIN_KEEP_ROUNDS: int = 1

# 压缩工具保留轮次的最大值
COMPRESS_HISTORY_MAX_KEEP_ROUNDS: int = 10

# 压缩工具要求的最小历史消息数
COMPRESS_HISTORY_MIN_MESSAGES: int = 10
