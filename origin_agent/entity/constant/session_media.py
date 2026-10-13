"""主会话媒体实例的身份、清单和发送控制常量。"""

# 清单分页默认起点（实例序号，0-indexed）。
SESSION_MEDIA_DEFAULT_OFFSET: int = 0
# 清单默认页大小与单次最大页大小（媒体实例数）。
SESSION_MEDIA_DEFAULT_LIMIT: int = 100
SESSION_MEDIA_MAX_LIMIT: int = 500
# 逻辑来源展示上限（Unicode 码点）。
SESSION_MEDIA_LABEL_MAX_CHARS: int = 512
# 持久实例身份：uuid4 的 32 位小写十六进制表示。
SESSION_MEDIA_ID_PATTERN: str = r"[0-9a-f]{32}"
# 关闭实例且转发不可用时的英文占位模板。
SESSION_MEDIA_PLACEHOLDER_TEMPLATE: str = "messages/media_unavailable.txt"
# 按需预览允许的 MIME；不把任意媒体作为 HTML 执行。
SESSION_MEDIA_PREVIEW_MIME_TYPES: frozenset[str] = frozenset({
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml",
    "audio/wav", "audio/mpeg", "video/mp4",
})
# 只有 HTTP 400 并命中明确模态拒绝时才允许占位；媒体变量按当前类型展开。
SESSION_MEDIA_UNSUPPORTED_ERROR_PATTERNS: tuple[str, ...] = (
    "model only supports text input",
    "model does not support {media_type}",
    "model doesn't support {media_type}",
    "{media_type} input is not supported",
    "unsupported modality",
)
