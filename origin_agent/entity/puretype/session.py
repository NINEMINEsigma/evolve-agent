from enum import Enum
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from typing import Any, Literal

from ._base import MessageContent, TypedMessageContent
from .llm import MessageMetrics
from .session_visual import SessionVisualResources

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


class SessionTagsUpdateRequest(BaseModel):
    """会话标签更新请求。"""

    model_config = ConfigDict(extra="forbid")

    tags: list[str] = Field(default_factory=list)


class SessionTitleUpdateRequest(BaseModel):
    """会话标题更新请求。"""

    model_config = ConfigDict(extra="forbid")

    title: str = ""


class SessionMessageEditRequest(BaseModel):
    """历史消息编辑请求。"""

    model_config = ConfigDict(extra="forbid")

    content: TypedMessageContent | None = None
    visible_characters: list[str] | None = None


class SessionRegenerateRequest(BaseModel):
    """重新生成请求。"""

    model_config = ConfigDict(extra="forbid")

    message_index: int | None = None
    llm_profile_name: str
    require_tool_call: StrictBool = False


class SessionMergeRequest(BaseModel):
    """会话合并或单源分支请求。"""

    model_config = ConfigDict(extra="forbid")

    sources: list[str] = Field(default_factory=list)


class MainSessionActivitySource(str, Enum):
    """触发一次主会话活动的来源。"""

    user_message = "user_message"
    dynamic_endpoint = "dynamic_endpoint"
    subagent_feedback = "subagent_feedback"
    cron = "cron"
    regenerate = "regenerate"
    resume = "resume"
    other = "other"
    mixed = "mixed"


class MainSessionActivityPhase(str, Enum):
    """主会话当前活动所处的运行阶段。"""

    queued = "queued"
    preparing = "preparing"
    waiting_first_token = "waiting_first_token"
    streaming = "streaming"
    waiting_approval = "waiting_approval"
    waiting_tool = "waiting_tool"


class MainSessionActivitySnapshot(BaseModel):
    """不持久化的主会话活动快照。"""

    activity_id: str
    revision: int = Field(ge=1)
    source: MainSessionActivitySource
    phase: MainSessionActivityPhase
    stream_id: str | None = None
    character_name: str | None = None


class SessionTabCapabilities(BaseModel):
    """Lightweight capability state for content-dependent session tabs."""

    session_id: str
    media_count: int = Field(ge=0)
    variables_available: bool


class SessionRuntimeStatus(BaseModel):
    """会话存在性、连接占用、视觉资源与当前运行活动的统一 REST 响应。"""

    session_id: str
    exists: bool
    occupied: bool
    processing: bool
    activity: MainSessionActivitySnapshot | None = None
    visual_resources: SessionVisualResources | None = None


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


class SessionHistoryRowKind(str, Enum):
    """前端历史投影行类型。"""

    message = "message"
    tool_card = "tool_card"


class SessionHistoryToolCardStatus(str, Enum):
    """History 中工具调用卡片的终态。"""

    succeeded = "succeeded"
    failed = "failed"
    missing_result = "missing_result"


class SessionHistoryToolCard(BaseModel):
    """一个工具调用卡片的只读 History 投影。"""

    tool_call_id: str
    tool_name: str
    request_args: dict[str, Any] = Field(default_factory=dict)
    request_args_raw: str | None = None
    status: SessionHistoryToolCardStatus
    result_content: str | list[dict[str, Any]] | None = None
    result_history_index: int | None = None
    tool_call_meta: dict[str, Any] | None = None
    embedded_messages: list[dict[str, Any]] | None = None
    is_error: bool = False


class SessionHistorySkeletonRow(BaseModel):
    row_id: str
    history_index: int
    row_kind: SessionHistoryRowKind
    role: str
    character_name: str | None = None
    tool_index: int | None = None
    tool_call_id: str | None = None
    is_system_status: bool = False
    # 轮次导航条条目文本：仅 user 普通消息行填充，空白折叠后截断
    content_excerpt: str | None = None


class SessionHistorySkeletonResponse(BaseModel):
    session_id: str
    start_index: int
    history_count: int
    row_count: int
    rows: list[SessionHistorySkeletonRow] = Field(default_factory=list)


class SessionHistoryContentRow(SessionHistorySkeletonRow):
    content: str | list[dict[str, Any]]
    visible_characters: list[str] | None = None
    response_characters: list[str] | None = None
    message_suffix: str | None = None
    dynamic_message_suffix: str | None = None
    reasoning_content: str | None = None
    requires_response: bool | None = None
    tool_card: SessionHistoryToolCard | None = None
    # 孤立 ToolResultMessage 的兼容/降级字段
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_args_raw: str | None = None
    tool_call_meta: dict[str, Any] | None = None
    metrics: MessageMetrics | None = None


class SessionHistoryPageResponse(BaseModel):
    session_id: str
    start_index: int
    end_index: int
    history_count: int
    rows: list[SessionHistoryContentRow] = Field(default_factory=list)


class SessionHistoryImageResource(BaseModel):
    resource_id: str
    url: str
    alt: str = ""


class SessionHistoryDownloadResource(BaseModel):
    resource_id: str
    url: str
    filename: str
    size: int | None = None


class SessionHistoryResourcesResponse(BaseModel):
    session_id: str
    history_count: int
    images: list[SessionHistoryImageResource] = Field(default_factory=list)
    downloads: list[SessionHistoryDownloadResource] = Field(default_factory=list)


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
    is_system_status: bool = False
    """标记该消息为系统状态消息（对 LLM 不可见，仅前端展示用）。"""


class SessionTerminationResult(BaseModel):
    """会话终结结果；元数据失败不阻止归档，只通过 warnings 返回。"""

    terminated: bool
    session_id: str
    error: str | None = None
    metadata_warnings: list[str] = Field(default_factory=list)


class SessionMessageEditResult(BaseModel):
    """编辑会话消息的稳定结果。"""

    updated: bool
    session_id: str
    index: int | None = None
    role: str | None = None
    content: str | dict[str, Any] | list[dict[str, Any]] | None = None
    visible_characters: list[str] | None = None
    error: str | None = None


class SessionMessageDeletionResult(BaseModel):
    """删除会话消息的稳定结果，兼容批量删除和单条配对删除。"""

    deleted: bool
    session_id: str | None = None
    removed_indices: list[int] = Field(default_factory=list)
    remaining_count: int | None = None
    history_count: int | None = None
    token_usage: int | None = None
    context_tokens: int | None = None
    error: str | None = None


class SessionRegenerateResult(BaseModel):
    """重新生成会话消息前置处理的稳定结果。"""

    regenerate: bool
    session_id: str
    last_user_content: str = ""
    remaining_count: int = 0
    message_index: int | None = None
    message_suffix: str | None = None
    dynamic_message_suffix: str | None = None
    visible_characters: list[str] | None = None
    response_characters: list[str] | None = None
    error: str | None = None


class SessionToolResources(BaseModel):
    """会话可恢复工具资源的稳定快照。"""

    session_id: str
    task_progress: dict[str, Any] = Field(default_factory=dict)
    clipboard_display: dict[str, Any] = Field(default_factory=dict)
    dynamic_endpoints: list[dict[str, Any]] = Field(default_factory=list)


class SessionRuntimeResourceTransferResult(BaseModel):
    """会话旋转时运行态资源迁移的稳定结果。"""

    old_sid: str
    new_sid: str
    tool_resources_error: str | None = None


class SessionMergeResult(BaseModel):
    """会话合并或单源分支的稳定结果。"""

    merged: bool
    session_id: str | None = None
    sources: list[str] = Field(default_factory=list)
    error: str | None = None


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
    # 前端消息保留自己的 Profile 名称；None 仅供内部消息表示沿用当前配置。
    llm_profile_name: str | None = None
    # 单次输入的生成要求，不投影到消息或工具结果正文。
    require_tool_call: StrictBool = False
    # SP-5 bugfix：回显移到消费侧，client_message_id 随消息携带供 _append_queued_messages 回显
    client_message_id: str | None = None


# ---------------------------------------------------------------------------
# Tool Chain Compression — 工具链压缩
# ---------------------------------------------------------------------------

class ToolChainSpan(BaseModel):
    """历史中一条可压缩工具链的索引区间（半开区间 [start, end)）。"""

    start: int
    end: int


# ---------------------------------------------------------------------------
# Main Session Interrupt — 主会话中断结果（权威响应）
# ---------------------------------------------------------------------------

class MainSessionInterruptResult(BaseModel):
    """主会话强制中断的权威结果，由 HTTP /api/interrupt/{sid} 返回。"""

    accepted: bool
    """中断请求是否被接受执行。"""

    status: Literal["idle", "cancelled", "timeout", "failed", "not_found"]
    """中断后状态：idle=无活动任务；cancelled=已取消并收尾；timeout=清理超时；failed=清理异常；not_found=会话不存在。"""

    session_id: str
    """目标主会话 ID。"""

    reason: str = ""
    """中断原因标记（user / idle-timeout 等）。"""

    error: str | None = None
    """失败或超时时的错误说明。"""