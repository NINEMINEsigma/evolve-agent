"""纯类型定义 — 不包含任何方法，仅作为数据标记使用。"""

from enum import Enum


class Role(str, Enum):
    """OpenAI 消息格式中的会话角色。"""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"