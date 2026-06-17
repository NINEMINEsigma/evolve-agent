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

# 子进程默认超时（秒）— 用于 pip install、scp 传输、前端构建等子进程调用
SUBPROCESS_TIMEOUT_DEFAULT: int = 120

# Playwright 页面操作默认超时（毫秒）— 用于 Mermaid/Excalidraw 等浏览器渲染场景
PLAYWRIGHT_PAGE_TIMEOUT_MS: int = 120_000

# 审批模型加载等待超时（秒）— 等待本地 GGUF 模型从 loading 变为 ready
APPROVAL_MODEL_LOAD_TIMEOUT: int = 120

# 审批请求等待超时（秒）— 等待用户在前端确认工具调用
APPROVAL_WAIT_TIMEOUT: int = 120

# cron 任务执行超时（秒）— 单次定时任务的最大运行时间
CRON_TASK_TIMEOUT: int = 300

# ffmpeg 命令执行默认超时（秒）
FFMPEG_DEFAULT_TIMEOUT: int = 300