"""
只含有不包含任何方法定义的类型定义
"""

from enum import Enum
from pydantic import BaseModel, Field

from typing import * # type: ignore


class Role(str, Enum):
    """OpenAI 消息格式中的会话角色。"""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class ToolDangerLevel(str, Enum):
    readonly = "readonly"
    write = "write"
    dangerous = "dangerous"


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