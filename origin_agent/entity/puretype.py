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