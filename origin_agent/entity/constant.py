"""全局常量定义。"""

import re
from datetime import timezone

# ============================================================================
# 版本定义
# ============================================================================

History_Version = "v1"


# ============================================================================
# 用户与主agent的角色名定义
# ============================================================================

SYSTEM_CHARACTER_NAME: str = "system"
USER_CHARACTER_NAME: str = "end-user"
MAIN_AGENT_CHARACTER_NAME: str = "main-agent"
# 使用时用于在列表字段指代所有agents
ALL_AGENTS_CHARACTER_REF_NAME: str = "all-agents"


# ============================================================================
# 自定义插件目录
# ============================================================================

# 本地 GGUF 模型文件存放目录名
CUSTOM_MODELS_DIR: str = "custom_models"

# 自定义插件目录
CUSTOM_TOOLS_DIR: str = "custom_tools"


# ============================================================================
# 内部文件位置
# ============================================================================

# 工具 allowlist 持久化文件名 — 存放于 workspace/ 下，用于记录用户始终允许的工具调用
TOOL_ALLOWLIST_FILENAME: str = "tool_allowlist.json"

# 会话索引文件名 — 存放于 workspace/ 下
SESSION_INDEX_FILENAME: str = "_sessions.json"

# 会话存储目录名（位于 workspace/ 下）
SESSIONS_DIR_NAME: str = "sessions"

# easysave 会话索引的 namespace key
SESSION_EASYSAVE_KEY: str = "_sessions"


# ============================================================================
# 截断/预览上限
# ============================================================================

# 日志/预览截断长度（字符数）— 用于 logger 输出、错误消息中的短预览
LOG_PREVIEW_CHARS: int = 200

# 工具结果/原始参数预览截断长度（字符数）— 用于工具返回值预览、JSON 参数预览
TOOL_RESULT_PREVIEW_CHARS: int = 2000

# 工具结果日志单个参数的截断长度（字符数）— 用于工具结果日志输出
TOOL_RESULT_LOG_ARGUMENT_CHARS: int = 100

# 工具结果完整内容保存截断阈值（字符数）— 超过时结果写入文件，仅返回预览
# 目前设置为一百万, 尽可能不再阻塞大部分工具调用, 同时组织真正的无限大文件输出
# TODO: 以后还需要更优的策略
TOOL_RESULT_SAVE_THRESHOLD_CHARS: int = 1000000

# 自动内容截断长度（字符数）— 用于自动内容截断
AUTO_CONTENT_MAX: int = 500000

# 自动标题生成时单条消息内容截断长度（字符数）— user/assistant 消息过长时截断后拼入 prompt
AUTO_TITLE_CONTENT_MAX: int = AUTO_CONTENT_MAX

# 会话标签生成时历史消息 JSON 截断长度（字符数）— 控制 tags prompt 的上下文长度
AUTO_TAGS_CONTENT_MAX: int = AUTO_CONTENT_MAX

# 会话合并时直接拼接摘要的字符阈值，超过则截断
MERGE_CONCAT_THRESHOLD: int = AUTO_CONTENT_MAX

# 会话摘要生成时历史输入截断上限（字符数）— 暂时设为极大值，后续再细化
SUMMARY_INPUT_MAX_CHARS: int = 1_000_000_000

# 会话旋转/合并继承时，旧会话保留的尾部轮次数
INHERIT_LAST_ROUNDS: int = 10

# 元数据提取器角色名 — 用于标题/标签/摘要生成时 LLM 客户端的 character 参数，
# 明确声明"这不是 agent 在说话，是元数据提取工具在工作"。
# 对 BaseMessage 无技术效果，但语义上隔离了 agent 角色和元数据生成角色。
META_EXTRACTOR_CHARACTER: str = "__meta_extractor__"


# ============================================================================
# 超时
# ============================================================================

# 子进程默认超时（秒）— 用于 pip install、scp 传输、前端构建等子进程调用
SUBPROCESS_TIMEOUT_DEFAULT: int = 120

# 子进程短超时 (秒) - 用于检查版本的指令等
SUBPROCESS_SHORT_TIMEOUT_DEFAULT: int = 5

# 子进程软清理等待时间, 到时后强杀进程
SUBPROCESS_SOFT_CLEANUP_WAIT_TIME: int = 5

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

# write_file 完全覆盖模式的内容上限（字符数）
WRITE_FILE_MAX_CHARS: int = 100000

# edit_file 增量编辑模式的内容上限（字符数）
EDIT_FILE_MAX_CHARS: int = 100000

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

# agentspace 下的上传子目录名 — 文件上传的目标物理目录
UPLOADS_DIR_NAME: str = "uploads"

# 上传文件在沙箱中的逻辑路径前缀 — 如 ws:uploads/screenshot.png
UPLOADS_WS_PREFIX: str = f"ws:{UPLOADS_DIR_NAME}/"

# 静态文件 HTTP 路由前缀 — 前端通过此 URL 访问 agentspace 下的文件
# 注意：此路由名恰好与上传目录名相同，但服务于整个 agentspace（不仅是 uploads 子目录）
STATIC_FILE_HTTP_PREFIX: str = "/uploads"

# 下载路由 HTTP 前缀 — 触发浏览器 attachment 下载
DOWNLOADS_HTTP_PREFIX: str = "/downloads"

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

# web_fetch 内容字符上限 — 超过时完整内容保存到文件，仅返回预览
WEB_FETCH_MAX_CHARS: int = 50000


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
# DEPRECATED: 已改为每个 subagent 独立存储在 agentspace/subagents/ 下，
# 保留此常量仅作为历史兼容参考。
SUBAGENT_STORE_FILENAME: str = "subagents.json"

# 子 Agent 配置存放目录名（位于 agentspace 下）
SUBAGENT_DIR_NAME: str = "subagents"

# 单个子 Agent 配置文件后缀（easysave 序列化格式）
SUBAGENT_SETTING_SUFFIX: str = ".es"

# 子 Agent 注册表索引文件名
SUBAGENT_INDEX_FILENAME: str = "_index.json"

# 子 Agent 注册名允许的字符：英文字母、数字、中文、下划线、连字符
SUBAGENT_NAME_PATTERN: str = r"^[a-zA-Z0-9\u4e00-\u9fa5_-]+$"

# 子 Agent 最大同时活跃数量 — 超出上限的子 Agent 进入等待队列
SUBAGENT_MAX_ACTIVE: int = 50


# ============================================================================
# 多 Agent 协作
# ============================================================================

# 多 Agent 级联对话最大递归深度 — 防止循环引用
MULTI_AGENT_MAX_CASCADE_DEPTH: int = 10

# 多 Agent 模式下 JSON 格式回复解析失败最大重试次数
MULTI_AGENT_JSON_RETRIES: int = 5

# 多 Agent DSL 路由标签名
MULTI_AGENT_ROUTING_TAG_VISIBLE: str = "visible"
MULTI_AGENT_ROUTING_TAG_RESPONSE: str = "response"

# @response(...) 中表示"无响应"的简写
MULTI_AGENT_ROUTING_RESPONSE_NONE: str = "none"
MULTI_AGENT_ROUTING_RESPONSE_NULL: str = "null"

# DEPRECATED: SUBAGENT_READONLY_WHITELIST is no longer used.
# Subagents now inherit all non-multiagent tools automatically.
# Kept commented for reference.
# SUBAGENT_READONLY_WHITELIST: list[str] = [
#     "list_tools",
#     "list_uploads",
#     "read_file",
#     "probe_vision_capability",
#     "read_image",
#     "read_csv",
#     "read_docx",
#     "read_excel",
#     "read_pdf",
#     "list_directory",
#     "search_files",
#     "grep",
#     "web_fetch",
#     "web_search",
#     "media_info",
# ]


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
# Watching Service (background_service.py)
# ============================================================================

# Watching 服务长短间隔的最小值（秒）
WATCHING_MIN_INTERVAL: int = 3

# Watching 服务默认长间隔（秒）— 无标识符命中时使用
WATCHING_DEFAULT_LONG_INTERVAL: int = 180

# Watching 服务默认短间隔（秒）— 标识符命中后使用
WATCHING_DEFAULT_SHORT_INTERVAL: int = 12


# ============================================================================
# Skill
# ============================================================================

# Skill 文件关联扫描排除的目录/文件模式（黑名单）
IGNORED_DIRS: frozenset[str] = frozenset({
    "__pycache__", ".git", ".github", ".hub", ".archive",
    "node_modules", ".venv", "__pypackages__",
})

# 默认 skills 目录名称
DEFAULT_SKILLS_DIR: str = "skills"

# Inline shell 模板模式: {{ command }}
_INLINE_SHELL_RE = re.compile(r"\u007b\u007b\s*(.+?)\s*\u007d\u007d")