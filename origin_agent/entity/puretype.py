"""
只含有不包含任何方法定义的类型定义
"""

from enum import Enum
from pydantic import BaseModel, Field


class Role(str, Enum):
    """OpenAI 消息格式中的会话角色。"""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"