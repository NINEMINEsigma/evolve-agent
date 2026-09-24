"""HTTP 请求和网络内容限制常量。"""

# ============================================================================
# HTTP
# ============================================================================

# 默认 HTTP User-Agent 字符串 — 用于 web_search / web_fetch 等网络请求
DEFAULT_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# web_fetch 内容字符上限 — 超过时完整内容保存到文件，仅返回预览
WEB_FETCH_MAX_CHARS: int = 50000
