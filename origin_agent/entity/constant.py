"""全局常量定义。"""

from datetime import timezone

# Cron 定时任务 stdout 预览最大长度（传给 Agent 的预览字符数）
# 超过此长度时，Agent 会收到提示去日志文件查看完整输出
CRON_STDOUT_PREVIEW_MAX_LENGTH = 5000

# 上传文件名中携带的 UTC 时间戳格式，用于 list_uploads 按真实上传时间排序。
# 例如：20250617_123045_utc
UPLOAD_FILENAME_TIME_FORMAT = "%Y%m%d_%H%M%S_utc"

# 上传文件名时区（与 UPLOAD_FILENAME_TIME_FORMAT 配套使用）
UPLOAD_FILENAME_TIMEZONE = timezone.utc