"""
只含有不包含任何方法定义的类型定义
"""

from enum import Enum, IntFlag
from pydantic import BaseModel, ConfigDict, Field

from typing import * # type: ignore
from entity.constant import SYSTEM_CHARACTER_NAME

# ---------------------------------------------------------------------------
# Flags and Enums
# ---------------------------------------------------------------------------

class Role(str, Enum):
    """OpenAI 消息格式中的会话角色。"""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class ToolDangerLevel(str, Enum):
    """工具的危险等级。

    readonly  : 只读查询，无外部副作用。
    write       : 会写入文件系统或产生持久化副作用。
    dangerous   : 可能直接造成系统级损害，必须经审批后执行。
    """

    readonly = "readonly"
    write = "write"
    dangerous = "dangerous"


class ToolAvailability(IntFlag):
    """工具的可用范围（位掩码）。

    MAIN        : 仅 ParentAgent 可用。
    SUBAGENT    : 仅子 agent 可用。
    MULTI_AGENT : 多 Agent 协作模式可用。
    EVERY       : 所有模式均可用（MAIN | SUBAGENT | MULTI_AGENT）。
    """

    MAIN = 1
    SUBAGENT = 2
    MULTI_AGENT = 4
    EVERY = MAIN | SUBAGENT | MULTI_AGENT


# ---------------------------------------------------------------------------
# Skills Types
# ---------------------------------------------------------------------------

SkillPayload = dict[str, Any]
"""Serializable dict representing a loaded skill.

Keys:
    success: bool
    name: str
    path: str (relative path within the skills directory)
    skill_dir: str (absolute path to the skill directory)
    content: str (rendered markdown body)
    raw_content: str (unrendered markdown body)
    frontmatter: dict
    description: str
    category: str | None
    tags: list[str]
    linked_files: dict[str, list[str]]
    setup_needed: bool
    setup_note: str | None
    readiness_status: str
    error: str | None (on failure)
"""

SkillInfo = dict[str, Any]
"""Minimal skill metadata for listing.

Keys:
    name: str
    description: str
    category: str | None
    tags: list[str]
    path: str
    skill_dir: str
"""


# ---------------------------------------------------------------------------
# Loop Types
# ---------------------------------------------------------------------------

class Loop(str, Enum):
    '''
    用于映射运行时主会话使用的loop
    '''
    parent = "parent"
    multi = "multi"


class SessionStatus(str, Enum):
    """会话生命周期状态。"""
    active = "active"
    archived = "archived"


class LoopMeta(BaseModel):
    loopType: Loop = Loop.parent
    '''
    对应的loop类型
    '''
    agents: list[str]|None = None
    '''
    mutli loop时用于指定导入的agents
    '''


# ---------------------------------------------------------------------------
# Approval Types
# ---------------------------------------------------------------------------

class ApprovalOutcome(BaseModel):
    """
    审批流程的最终结果。
    """
    denied: bool = False
    """
    审批结果为 deny
    """
    deny_result: dict | None = None
    """
    deny 时的错误 dict，包含 error/denied/denied_by 字段
    """
    approved_args: dict = Field(default_factory=dict, description="审批通过后的 args 引用（已原地设置 _pre_approved / _approval_action）")


class ApprovalResult(BaseModel):
    """
    单次审批结果。与 ApprovalOutcome 不同，此类型直接对应审批后的 action 决策。
    """
    action: str
    """
    "allow_once" | "allow_always" | "deny"
    """
    deny_reason: str | None = None
    """
    拒绝原因，仅 action == "deny" 时有效
    """
    denied_by: str = SYSTEM_CHARACTER_NAME
    """
    拒绝来源："model"（脱手模式LLM）、"user"（人工）、SYSTEM_CHARACTER_NAME（超时/断开等）
    """


class ToolCallMeta(BaseModel):
    """工具调用的时间元信息。

    在 ToolExecutor 中自动收集并注入到工具返回结果的 ``_meta`` 字段。
    ``application_time`` 为人类可读的本地时间字符串，精确到毫秒；
    其余字段均为相对于 ``application_time_ms`` 的毫秒偏移。
    """
    application_time: str
    """人类可读的申请时间，格式 ``YYYY-MM-DD HH:MM:SS.mmm``。"""
    application_time_ms: int
    """申请时间的绝对毫秒时间戳，供机器计算使用。"""
    approval_duration_ms: int
    """审批耗时（毫秒），readonly 工具为 0。"""
    invocation_start_offset_ms: int
    """从申请到开始调用 handler 的毫秒偏移。"""
    invocation_duration_ms: int
    """handler 实际执行的毫秒数。"""
    end_time_offset_ms: int
    """从申请到工具调用完成的毫秒偏移。"""


class ToolAllowlistEntry(BaseModel):
    """
    工具 allowlist 中的单条永久授权记录。
    """
    tool: str
    """
    工具名称
    """
    args: dict = Field(default_factory=dict)
    """
    标准化的工具参数字典（已排除内部标记字段）
    """


# ---------------------------------------------------------------------------
# Cron Types
# ---------------------------------------------------------------------------

class CronTaskInfo(BaseModel):
    """定时任务信息（供 Handler 层与 API 层共用）。"""
    task_id: str
    name: str
    schedule_type: str
    schedule_value: str
    command: list[str]
    should_schedule: bool
    next_run: str | None = None  # ISO 格式时间戳，未调度时为 None
    run_count: int = 0
    last_run: str | None = None  # ISO 格式时间戳，从未执行时为 None
    log_path: str = ""


# ---------------------------------------------------------------------------
# LLM Types
# ---------------------------------------------------------------------------

class ToolCall(BaseModel):
    """LLM 返回的工具调用描述。"""
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    arguments: dict[str, Any] = {}


class Usage(BaseModel):
    """LLM 提供商返回的 token 消耗。"""
    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMResponse(BaseModel):
    """非流式 LLM 响应的完整内容。"""
    model_config = ConfigDict(frozen=True)

    content: str = ""
    tool_calls: list[ToolCall] = []
    finish_reason: str = "stop"
    reasoning_content: str | None = None
    """DeepSeek thinking-mode 载荷 — 在后续回合中必须回传。"""
    reasoning_field_name: str | None = None
    """原始响应中携带 reasoning 的字段名，用于在后续回传时保持字段一致。"""
    usage: Usage = Usage()


class StreamChunk(BaseModel):
    """流式 LLM 响应的一个片段。"""
    model_config = ConfigDict(frozen=True)

    content_delta: str | None = None
    reasoning_delta: str | None = None
    """DeepSeek thinking-mode 增量 — 仅用于展示。"""
    reasoning_field_name: str | None = None
    """当前 reasoning_delta 对应的原始字段名（如 reasoning_content / reasoning）。"""
    tool_call: ToolCall | None = None
    """当前 chunk 中首次完整出现的 tool_call（用于工具调用开始通知）。"""
    finish_reason: str | None = None
    usage: Usage | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Subagent Types
# ---------------------------------------------------------------------------

class SubagentProfile(BaseModel):
    """子 Agent 注册时冻结的 LLM 配置快照，持久化到 agentspace/subagents/。"""

    base_url: str
    """LLM API 端点地址。"""

    model: str
    """模型名称。"""

    api_key: str | None = None
    """API 密钥，本地模型可省略。"""

    system_prompt_paths: list[str] = Field(default_factory=list)
    """自定义系统提示词文件路径列表（沙箱逻辑路径）。"""

    max_output_tokens: int = 0
    """单次 LLM 输出的最大 token 数。"""

    max_context_tokens: int = 0
    """上下文窗口 token 上限，用于旋转控制。"""

    client_type: str = "openai_client"
    """LLM 客户端模块名，对应 custom_llm_client/<name>.py。"""


# ---------------------------------------------------------------------------
# Chat / Gateway Types
# ---------------------------------------------------------------------------

class SessionInfo(BaseModel):
    """会话元数据，用于 SessionManager._sessions 的内部存储与对外输出。

    `parent` 是 `parents[0]` 的冗余字段，供前端直接消费；
    磁盘持久化时由 `_write_index` 的 `clean.pop("parent")` 剔除，不冗余存储。
    """

    id: str
    """会话 ID（= _sessions 的 key）。"""

    status: SessionStatus = SessionStatus.active
    """会话生命周期状态。"""

    created_at: float = 0.0
    """创建时间（Unix 时间戳）。"""

    title: str = ""
    """会话标题。"""

    parents: list[str] = Field(default_factory=list)
    """父会话 ID 列表（支持多父合并）。"""

    parent: str | None = None
    """parents[0] if parents else None — 冗余字段，供前端直接消费。"""

    continuation: str | None = None
    """后续会话 ID（归档时指向继承者）。"""

    pinned: bool = False
    """是否置顶。"""

    last_activity_at: float = 0.0
    """最后活动时间（Unix 时间戳）。"""

    tags: list[str] = Field(default_factory=list)
    """会话标签列表。"""

    loop_type: Loop = Loop.parent
    """运行时主会话使用的 loop 类型。"""

    agents: list[str] | None = None
    """multi loop 时指定的 agents 列表。"""


class MessageType(str, Enum):
    """WebSocket 消息类型枚举。"""

    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    CONFIRM_REQUEST = "confirm_request"
    CONFIRM_RESPONSE = "confirm_response"
    ASK_REQUEST = "ask_request"
    ASK_RESPONSE = "ask_response"
    INTERRUPT = "interrupt"
    ERROR = "error"
    SYSTEM = "system"
    FILE_UPLOAD = "file_upload"
    HANDSFREE_MODE = "handsfree_mode"
    TASK_PROGRESS = "task_progress"
    CLIPBOARD_DISPLAY = "clipboard_display"
    STREAM_DELTA = "stream_delta"
    STREAM_DONE = "stream_done"
    PING = "ping"
    PONG = "pong"
    SUBAGENT_UPDATE = "subagent_update"
    AGENTSPACE_LOCK = "agentspace_lock"


class Message(BaseModel):
    """WebSocket 消息模型。"""

    type: MessageType
    session_id: str = ""
    content: Optional[Any] = None
    tool: str | None = None
    args: Optional[dict[str, Any]] = None
    result: Optional[Any] = None
    message: str | None = None  # ERROR 类型使用
    request_id: str | None = None  # confirm_request / confirm_response 使用
    action: str | None = None      # confirm_response：allow_once | allow_always | deny
    deny_reason: str | None = None  # confirm_response：拒绝原因
    denied_by: str | None = None    # confirm_response：拒绝来源 (model/user/system)
    filename: str | None = None    # FILE_UPLOAD：原始文件名
    mime_type: str | None = None   # FILE_UPLOAD：MIME 类型
    file_data: str | None = None   # FILE_UPLOAD：base64 编码的文件内容
    local_path: str | None = None  # FILE_UPLOAD：本地文件路径（同盘时优先硬链接）
    # ask_request / ask_response 相关字段
    question: str | None = None    # ASK_REQUEST：问题文本
    options: Optional[list] = None    # ASK_REQUEST：选项列表 [{label, value}]
    option: str | None = None      # ASK_RESPONSE：选中的选项值
    custom_text: str | None = None # ASK_RESPONSE：自定义输入文本
    # stream 相关字段
    stream_id: str | None = None   # STREAM_DELTA / STREAM_DONE：流标识
    delta: str | None = None       # STREAM_DELTA：文本增量
    reasoning_delta: str | None = None  # STREAM_DELTA：reasoning 增量
    finish_reason: str | None = None    # STREAM_DONE：结束原因或错误
    target_sessions: Optional[list[str]] = None  # USER_MESSAGE：目标会话列表
    # 多 Agent 模式：用户消息的可见性和响应指定
    visible_characters: Optional[list[str]] = None   # USER_MESSAGE：可见角色列表
    response_characters: Optional[list[str]] = None  # USER_MESSAGE：需响应角色列表
    # tool_call / tool_result / confirm_request 相关字段
    tool_call_id: str | None = None  # TOOL_CALL / TOOL_RESULT：工具调用 ID
    character_name: str | None = None  # 消息发送者角色名
    index: int | None = None  # 消息在持久化历史中的索引
    client_message_id: str | None = None  # 前端生成的乐观消息 ID，用于回显去重
    message_suffix: str | None = None  # 用户消息固定后缀（如 fixator 上下文）
    dynamic_message_suffix: str | None = None  # 用户消息动态后缀（如 memory/hooks 上下文）
    tool_call_meta: Optional[dict[str, Any]] = None  # TOOL_RESULT：工具调用时间元信息
    emoji: Optional[str] = None  # 工具调用/审批请求的图标


# ---------------------------------------------------------------------------
# Session Message Entry — 前端会话历史展示用的单条消息序列化模型
# ---------------------------------------------------------------------------

class SessionMessageEntry(BaseModel):
    """前端会话历史展示用的单条消息序列化模型。

    替代旧版 get_session_messages 中跨模块传播的 dict[str, Any]。
    所有可选字段默认 None，序列化时通过 exclude_none=True 省略。
    """
    role: str
    content: str | list[dict[str, Any]]
    index: int
    character_name: str | None = None
    visible_characters: list[str] | None = None
    response_characters: list[str] | None = None
    message_suffix: str | None = None
    dynamic_message_suffix: str | None = None
    reasoning_content: str | None = None
    requires_response: bool | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_meta: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# LSP Types
# ---------------------------------------------------------------------------

class LSPState(str, Enum):
    """LSP server 生命周期状态。

    IDLE      : 未启动，无 pyright 进程运行。
    STARTING  : 正在启动 pyright 并等待初始化握手 + 索引就绪。
    READY     : pyright 已就绪，可以接受查询请求。
    """

    IDLE = "idle"
    STARTING = "starting"
    READY = "ready"


class LSPDiagnostic(BaseModel):
    """单条 LSP 诊断信息。"""
    model_config = ConfigDict(frozen=True)

    severity: str  # "error" | "warning" | "information" | "hint"
    line: int      # 1-indexed
    column: int    # 1-indexed (character offset)
    end_line: int
    end_column: int
    message: str
    source: str = "pyright"
    code: str | None = None


class LSPReference(BaseModel):
    """单条引用位置。"""
    model_config = ConfigDict(frozen=True)

    file: str       # 逻辑路径 (如 "fork:main.py")
    line: int       # 1-indexed
    column: int     # 1-indexed
    end_line: int
    end_column: int
    preview: str    # 匹配行文本


class LSPDefinition(BaseModel):
    """符号定义位置。"""
    model_config = ConfigDict(frozen=True)

    file: str | None  # 逻辑路径，None 表示未找到
    line: int
    column: int
    end_line: int
    end_column: int
    preview: str


class LSPSymbol(BaseModel):
    """文件内符号。"""
    model_config = ConfigDict(frozen=True)

    name: str
    kind: str       # LSP SymbolKind 名称 (如 "Function", "Class", "Variable")
    line: int
    column: int
    end_line: int
    end_column: int
    detail: str | None = None
    children: list["LSPSymbol"] = Field(default_factory=list)