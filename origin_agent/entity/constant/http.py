"""HTTP 请求和网络内容限制常量。"""

from enum import Enum


class GatewayErrorCode(str, Enum):
    """网关明确业务拒绝的稳定机器码；不表示未知内部故障。"""

    APPLICATION_STOPPING = "application_stopping"
    SESSION_NOT_FOUND = "session_not_found"
    SESSION_NOT_READY = "session_not_ready"
    SESSION_ROTATING = "session_rotating"
    SESSION_ARCHIVED = "session_archived"
    SESSION_BUSY = "session_busy"
    COLLOQUY_OPERATION_FORBIDDEN = "colloquy_operation_forbidden"
    SESSION_DELETING = "session_deleting"
    FILE_CHANGES_BUSY = "file_changes_busy"
    MESSAGE_EDIT_REJECTED = "message_edit_rejected"
    MESSAGES_DELETE_REJECTED = "messages_delete_rejected"
    MESSAGE_DELETE_REJECTED = "message_delete_rejected"
    REGENERATE_REJECTED = "regenerate_rejected"
    HISTORY_INDEX_OUT_OF_RANGE = "history_index_out_of_range"
    INVALID_TAGS = "invalid_tags"
    MERGE_SOURCE_NOT_ARCHIVED = "merge_source_not_archived"
    SESSION_MERGE_REJECTED = "session_merge_rejected"
    INTERACTION_NOT_FOUND = "interaction_not_found"
    INTERRUPT_TIMEOUT = "interrupt_timeout"
    INTERRUPT_FAILED = "interrupt_failed"
    SHELL_NOT_FOUND = "shell_not_found"
    CRON_TASK_NOT_FOUND = "cron_task_not_found"
    DYNAMIC_ENDPOINT_NOT_FOUND = "dynamic_endpoint_not_found"
    PROFILE_NOT_FOUND = "profile_not_found"
    PROFILE_CONFLICT = "profile_conflict"
    METADATA_PROFILE_UNAVAILABLE = "metadata_profile_unavailable"
    METADATA_GENERATION_FAILED = "metadata_generation_failed"
    SANDBOX_INPUT_INVALID = "sandbox_input_invalid"
    SANDBOX_SPACE_CONFLICT = "sandbox_space_conflict"
    SANDBOX_SPACE_NOT_FOUND = "sandbox_space_not_found"
    SANDBOX_ACCESS_DENIED = "sandbox_access_denied"
    SANDBOX_SPACE_NAME_MISMATCH = "sandbox_space_name_mismatch"
    MEDIA_NOT_FOUND = "media_not_found"
    MEDIA_CONFLICT = "media_conflict"
    MEDIA_PREVIEW_INVALID = "media_preview_invalid"
    MEDIA_PREVIEW_UNSUPPORTED = "media_preview_unsupported"
    EXPORT_LIMIT = "export_limit"
    EXPORT_TIMEOUT = "export_timeout"
    EXPORT_CANCELLED = "export_cancelled"
    EXPORT_VIEWER_NOT_FOUND = "export_viewer_not_found"
    EXPORT_VIEWER_NOT_BUILT = "export_viewer_not_built"
    EXPORT_VIEWER_LIMIT = "export_viewer_limit"
    FILE_PICKER_TIMEOUT = "file_picker_timeout"
    DIRECTORY_PICKER_TIMEOUT = "directory_picker_timeout"
    FILE_PICKER_FAILED = "file_picker_failed"
    DIRECTORY_PICKER_FAILED = "directory_picker_failed"
    ROUTE_NOT_FOUND = "route_not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    HTTP_ERROR = "http_error"


# 新业务HTTP路径首段；只匹配完整首段，不匹配相似名称。
GATEWAY_BUSINESS_HTTP_PREFIXES: tuple[str, ...] = ("/api", "/dynamic")
# 前端产物和文件服务的既有禁止缓存头；调用方不得原地修改。
HTTP_NO_CACHE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache",
}
# 需要UTF-8 charset的文本MIME前缀。
HTTP_TEXT_MIME_PREFIXES: tuple[str, ...] = (
    "text/", "application/json", "application/xml", "application/javascript",
)
# 需要文本charset的既有文件后缀。
HTTP_TEXT_MIME_EXTENSIONS: frozenset[str] = frozenset({
    ".html", ".htm", ".md", ".txt", ".log", ".json", ".csv", ".py", ".js",
    ".css", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".svg",
})
# 导出HTTP断开观察间隔，单位秒，不改变导出请求整体预算。
GATEWAY_EXPORT_DISCONNECT_POLL_SECONDS: float = 0.25

# ============================================================================
# HTTP
# ============================================================================

# 默认 HTTP User-Agent 字符串 — 用于 web_fetch 等网络请求
DEFAULT_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# web_fetch 内容字符上限 — 超过时完整内容保存到文件，仅返回预览
WEB_FETCH_MAX_CHARS: int = 50000
