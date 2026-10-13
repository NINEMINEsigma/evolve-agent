"""WebSocket 协议常量。"""

# ============================================================================
# WebSocket 协议
# ============================================================================

# 会话永久删除关闭码 — 通知前端停止按已删除的会话 ID 自动重连
WEBSOCKET_CLOSE_SESSION_DELETED: int = 4004

# SYSTEM 消息协议载荷 action 值 — 首条消息自动标题写入后通知前端单条目更新
SESSION_TITLE_UPDATED_ACTION: str = "session_title_updated"
