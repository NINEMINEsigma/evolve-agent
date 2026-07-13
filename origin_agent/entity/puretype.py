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

    MAIN      : 仅主 agent 可用。
    SUBAGENT  : 仅子 agent 可用。
    EVERY     : 主 agent 与子 agent 均可用（MAIN | SUBAGENT）。
    """

    MAIN = 1
    SUBAGENT = 2
    EVERY = MAIN | SUBAGENT


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