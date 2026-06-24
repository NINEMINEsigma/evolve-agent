"""全局常量定义。"""

from datetime import timezone

# ============================================================================
# 截断/预览上限
# ============================================================================

# 日志/预览截断长度（字符数）— 用于 logger 输出、错误消息中的短预览
LOG_PREVIEW_CHARS: int = 200

# 工具结果/原始参数预览截断长度（字符数）— 用于工具返回值预览、JSON 参数预览
TOOL_RESULT_PREVIEW_CHARS: int = 2000

# 自动标题生成时单条消息内容截断长度（字符数）— user/assistant 消息过长时截断后拼入 prompt
AUTO_TITLE_CONTENT_MAX: int = 5000

# 会话合并时直接拼接摘要的字符阈值，超过则截断
MERGE_CONCAT_THRESHOLD: int = 50000


# ============================================================================
# 超时
# ============================================================================

# 子进程默认超时（秒）— 用于 pip install、scp 传输、前端构建等子进程调用
SUBPROCESS_TIMEOUT_DEFAULT: int = 120

# 子进程短超时 (秒) - 用于检查版本的指令等
SUBPROCESS_SHORT_TIMEOUT_DEFAULT: int = 5

# 子进程软清理等待时间, 到时后强杀进程
SUBPROCESS_SOFT_CLEANUP_WAIT_TIME: int = 5

# Playwright 页面操作默认超时（毫秒）— 用于 Mermaid/Excalidraw 等浏览器渲染场景
PLAYWRIGHT_PAGE_TIMEOUT_MS: int = 120000

# 审批模型加载等待超时（秒）— 等待本地 GGUF 模型从 loading 变为 ready
APPROVAL_MODEL_LOAD_TIMEOUT: int = 120

# 审批请求等待超时（秒）— 等待用户在前端确认工具调用
APPROVAL_WAIT_TIMEOUT: int = 120

# cron 任务执行超时（秒）— 单次定时任务的最大运行时间
CRON_TASK_TIMEOUT: int = 300

# ffmpeg 命令执行默认超时（秒）
FFMPEG_DEFAULT_TIMEOUT: int = 300

# 指数退避基数（秒）
BACKOFF_BASE: float = 1.0

# 子 Agent 周期收集空闲触发时间（秒）— 父 Agent 消息队列空闲超过此时间后触发收集
# 推荐该值不要超过origin_agent\frontend\src\components\SubagentCountdown.tsx中设定的值
SUBAGENT_IDLE_TRIGGER_SECONDS: int = 20


# ============================================================================
# 文件系统 I/O 限制
# ============================================================================

# write_file / write_fork 完全覆盖模式的内容上限（字符数）
WRITE_FILE_MAX_CHARS: int = 10000

# edit_file 增量编辑模式的内容上限（字符数）
EDIT_FILE_MAX_CHARS: int = 10000

# read_file 单次读取最大行数（硬上限）
READ_FILE_MAX_LINES: int = 2000

# read_file 默认返回行数
READ_FILE_DEFAULT_LIMIT: int = 100

# write_file / append_file 截断时返回的尾部字符数 — 用于作为 edit_file 的 old_string 或继续追加
WRITE_FILE_TRUNCATION_TAIL: int = 25

# 文件类型嗅探采样字节数 — 通过检查前 N 字节中是否含空字节判断是否为文本文件
FILE_SNIFF_BYTES: int = 4096

# 支持的命名空间前缀元组 — 用于命令参数中的逻辑路径解析
NAMESPACE_PREFIXES: tuple[str, ...] = ("ws:", "fork:", "fix:", "skills:")


# ============================================================================
# 上传
# ============================================================================

# 文件名示例：20250617_123045_utc_a1b2c3d4_filename.ext
UPLOAD_TIME_RE_PATTERN = r"^(\d{8}_\d{6}_utc)_[a-f0-9]{8}_(.+)$"

# 上传文件名中携带的 UTC 时间戳格式，用于 list_uploads 按真实上传时间排序。
# 例如：20250617_123045_utc
UPLOAD_FILENAME_TIME_FORMAT = "%Y%m%d_%H%M%S_utc"

# 上传文件名时区（与 UPLOAD_FILENAME_TIME_FORMAT 配套使用）
UPLOAD_FILENAME_TIMEZONE = timezone.utc


# ============================================================================
# HTTP
# ============================================================================

# 默认 HTTP User-Agent 字符串 — 用于 web_search / web_fetch 等网络请求
DEFAULT_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


# ============================================================================
# LLM
# ============================================================================

# 审批模型上下文窗口 token 数默认值
APPROVAL_MODEL_N_CTX_DEFAULT: int = 4096

# 所有LLM解析的重试次数
LLM_RETRY_COUNT: int = 3


# ============================================================================
# Agent
# ============================================================================

# Agent 最大工具调用轮次上限 — 防止死循环
MAX_TOOL_TURNS: int = 90


# ============================================================================
# 子 Agent
# ============================================================================

# 子 Agent 注册表持久化文件名 — 存放于 workspace/ 下
SUBAGENT_STORE_FILENAME: str = "subagents.json"

# 子 Agent 最大同时活跃数量 — 超出上限的子 Agent 进入等待队列
SUBAGENT_MAX_ACTIVE: int = 5

# 子 Agent 系统预设 readonly 工具白名单 — 子 Agent 默认可用这些只读工具
# 此列表硬编码在代码中，仅能通过修改代码来调整；multiagent 工具集始终被硬排除（禁止递归）
SUBAGENT_READONLY_WHITELIST: list[str] = [
    "list_tools",
    "list_uploads",
    "read_file",
    "probe_vision_capability",
    "read_image",
    "read_csv",
    "read_docx",
    "read_excel",
    "read_pdf",
    "list_directory",
    "search_files",
    "grep",
    "web_fetch",
    "web_search",
    "media_info",
]


# ============================================================================
# Cron
# ============================================================================

# Cron 任务持久化文件名 — 存放于 workspace/ 下
CRON_STORE_FILENAME: str = "cron_jobs.json"

# Cron 定时任务 stdout 预览最大长度（传给 Agent 的预览字符数）
# 超过此长度时，Agent 会收到提示去日志文件查看完整输出
CRON_STDOUT_PREVIEW_MAX_LENGTH = 5000

# Cron 最小可设间隔/等待秒数（schedule_cron 和 wait_cron 共用）
CRON_MIN_INTERVAL_SECONDS: int = 3

# 每个会话最多允许的 Cron 任务数量
CRON_MAX_JOBS_PER_SESSION: int = 20


# ============================================================================
# 会话
# ============================================================================

# 会话索引文件名
SESSION_INDEX_FILENAME: str = "_sessions.json"