"""全局常量定义。"""

from datetime import timezone

# 日志/预览截断长度（字符数）— 用于 logger 输出、错误消息中的短预览
LOG_PREVIEW_CHARS: int = 200

# 工具结果/原始参数预览截断长度（字符数）— 用于工具返回值预览、JSON 参数预览
TOOL_RESULT_PREVIEW_CHARS: int = 2000

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

# write_file / write_fork 完全覆盖模式的内容上限（字符数）
WRITE_FILE_MAX_CHARS: int = 1000

# 支持的命名空间前缀元组 — 用于命令参数中的逻辑路径解析
NAMESPACE_PREFIXES: tuple[str, ...] = ("ws:", "fork:", "fix:", "skills:")

# 默认 HTTP User-Agent 字符串 — 用于 web_search / web_fetch 等网络请求
DEFAULT_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# 审批模型上下文窗口 token 数默认值
APPROVAL_MODEL_N_CTX_DEFAULT: int = 4096

# 文件类型嗅探采样字节数 — 通过检查前 N 字节中是否含空字节判断是否为文本文件
FILE_SNIFF_BYTES: int = 4096

# 自动标题生成时单条消息内容截断长度（字符数）— user/assistant 消息过长时截断后拼入 prompt
AUTO_TITLE_CONTENT_MAX: int = 5000

# 会话合并时直接拼接摘要的字符阈值，超过则截断
MERGE_CONCAT_THRESHOLD: int = 50000