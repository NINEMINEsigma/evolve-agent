from enum import Enum, IntFlag
from typing import Any

# ---------------------------------------------------------------------------
# Type Aliases
# ---------------------------------------------------------------------------

# 序列化后的消息内容——纯文本或多模态 blocks 列表
# TODO: 存在一些误用
MessageContent = str | list[dict[str, Any]]

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

    safe    : 永远安全且可逆
    write       : 可能产生被用于不可逆影响的产物
    dangerous   : 可能导致不可逆的危险影响, 必须经审批后执行
    critical    : 操作本身可能安全，但用户必须亲自许可，不可由模型代审批
    """

    safe = "safe"
    write = "write"
    dangerous = "dangerous"
    critical = "critical"


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
    TASKAGENT = 8
    """仅一次性任务 Agent (TaskAgentLoop) 可用。"""
    EVERY = MAIN | SUBAGENT | MULTI_AGENT | TASKAGENT
    """所有模式均可用（MAIN | SUBAGENT | MULTI_AGENT | TASKAGENT）。"""