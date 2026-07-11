"""
只含有不包含任何方法定义的类型定义
"""

from enum import Enum, IntFlag
from pydantic import BaseModel, Field

from typing import * # type: ignore

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
    denied_by: str = "system"
    """
    拒绝来源："model"（脱手模式LLM）、"user"（人工）、"system"（超时/断开等）
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