from enum import Enum
from pydantic import BaseModel, Field
from typing import Any

from ._base import MessageContent
from .llm import MessageMetrics, LLMProfile

# ---------------------------------------------------------------------------
# Loop Types
# ---------------------------------------------------------------------------

class Loop(str, Enum):
    '''
    用于映射运行时主会话使用的loop
    '''
    parent = "parent"
    multi = "multi"
    colloquy = "colloquy"


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
    metrics: MessageMetrics | None = None


# ---------------------------------------------------------------------------
# Token Usage Types
# ---------------------------------------------------------------------------

class TokenUsageRecord(BaseModel):
    """token 使用量持久化结构，对应 token_usage.json。"""

    token_usage: int = 0
    """会话累计 token 总消耗量。"""

    prompt_tokens: int = 0
    """最近一次 LLM 调用的 prompt token 数（已消耗上下文）。"""


# ---------------------------------------------------------------------------
# Queued Message — 会话消息队列元素（SP-4）
# ---------------------------------------------------------------------------

class QueuedMessage(BaseModel):
    """会话消息队列元素。content 保留原始 MessageContent，严禁扁平化。"""
    content: MessageContent
    character_name: str = ""
    source: str = ""
    timestamp: str = ""
    # SP-5 D1：可选元数据，仅 ws / dynamic-endpoint 来源使用；None 时消费侧回退缺省。
    visible_characters: list[str] | None = None
    response_characters: list[str] | None = None
    llm_profile: LLMProfile | None = None
    # SP-5 bugfix：回显移到消费侧，client_message_id 随消息携带供 _append_queued_messages 回显
    client_message_id: str | None = None