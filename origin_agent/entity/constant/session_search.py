"""会话搜索工具的结果和读取限制常量。"""

# ============================================================================
# 会话搜索 (session_search.py)
# ============================================================================

# RecallSession message 级结果默认上限
SESSION_SEARCH_MAX_MESSAGE_RESULTS_DEFAULT: int = 20

# RecallSession message 级结果硬上限
SESSION_SEARCH_MAX_MESSAGE_RESULTS_LIMIT: int = 50

# RecallSession history 级结果默认上限
SESSION_SEARCH_MAX_HISTORY_RESULTS_DEFAULT: int = 10

# RecallSession history 级结果硬上限
SESSION_SEARCH_MAX_HISTORY_RESULTS_LIMIT: int = 50

# ReadSession 默认读取消息条数
SESSION_SEARCH_READ_LENGTH_DEFAULT: int = 10

# ReadSession 读取消息条数硬上限
SESSION_SEARCH_READ_LENGTH_LIMIT: int = 100

# RecallSession 结果预览/摘要截断长度（字符数）
SESSION_SEARCH_PREVIEW_LENGTH: int = 200
