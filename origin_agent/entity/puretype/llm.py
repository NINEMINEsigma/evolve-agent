from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, ConfigDict, Field
from typing import Any

# ---------------------------------------------------------------------------
# LLM Types
# ---------------------------------------------------------------------------

class ToolCallRequest(BaseModel):
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


class MessageMetrics(BaseModel):
    """单条 LLM 响应的计时与 token 速度元信息。

    在 StreamConsumer.consume() 中基于 time.monotonic() 增量到达时间采集，
    通过 stream_done 事件实时推送到前端，并在 tool loop 结束后
    持久化到 session 目录下的 message_metrics.json。
    """

    reasoning_duration_ms: int = 0
    """推理阶段耗时（毫秒），基于首个到最后一个 reasoning_delta 的间隔。"""

    content_duration_ms: int = 0
    """正文阶段耗时（毫秒），基于首个到最后一个 content_delta 的间隔。"""

    completion_tokens: int = 0
    """本轮 LLM 调用的 completion_tokens（来自 Usage）。"""

    tokens_per_second: float = 0.0
    """token 输出速度 = completion_tokens / ((reasoning_ms + content_ms) / 1000）。"""


class LLMResponse(BaseModel):
    """非流式 LLM 响应的完整内容。"""
    model_config = ConfigDict(frozen=True)

    content: str = ""
    tool_calls: list[ToolCallRequest] = []
    finish_reason: str = "stop"
    reasoning_content: str | None = None
    """DeepSeek thinking-mode 载荷 — 在后续回合中必须回传。"""
    reasoning_field_name: str | None = None
    """原始响应中携带 reasoning 的字段名，用于在后续回传时保持字段一致。"""
    usage: Usage = Usage()
    metrics: MessageMetrics | None = None
    """本轮 LLM 调用的计时与 token 速度元信息（StreamConsumer 填充）。"""


class ToolCallDeltaPhase(str, Enum):
    """tool_call 参数生成期增量阶段。"""

    START = "start"
    APPEND = "append"
    DONE = "done"


class ToolCallDelta(BaseModel):
    """tool_call 参数生成期增量（仅展示用途，不参与聚合）。

    在 LLM 流式生成工具参数期间逐片产出，供前端打字机渲染。
    流末仍会产出完整 ToolCallRequest，聚合逻辑只认完整 tool_call。
    """
    model_config = ConfigDict(frozen=True)

    id: str = ""
    """provider 的 tool_call id；OpenAI 在首个 delta 才给出，start 时可能为空。"""

    index: int = 0
    """OpenAI 多 tool_call 交织时的 wire index；Anthropic 恒 0。"""

    name: str = ""
    """工具名（start 时给出）。"""

    args_delta: str = ""
    """原始 JSON 参数片段（append 时给出）。"""

    phase: ToolCallDeltaPhase


class StreamChunk(BaseModel):
    """流式 LLM 响应的一个片段。"""
    model_config = ConfigDict(frozen=True)

    content_delta: str | None = None
    reasoning_delta: str | None = None
    """DeepSeek thinking-mode 增量 — 仅用于展示。"""
    reasoning_field_name: str | None = None
    """当前 reasoning_delta 对应的原始字段名（如 reasoning_content / reasoning）。"""
    tool_call: ToolCallRequest | None = None
    """当前 chunk 中首次完整出现的 tool_call（用于工具调用开始通知）。"""
    tool_call_delta: ToolCallDelta | None = None
    """生成期 tool_call 参数增量（仅展示用途，不参与聚合）。"""
    finish_reason: str | None = None
    usage: Usage | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Modality Capability Types
# ---------------------------------------------------------------------------

class ModalityCapability(BaseModel):
    """探针探测的多模态能力缓存条目。

    每个字段对应一种模态在一种消息路径上的支持状态：
    - vision / audio / video: tool 消息中读取图片/音频/视频的能力
    - user_vision / user_audio / user_video: user 消息中读取图片/音频/视频的能力

    None 表示尚未探测，bool 表示探测结果。
    """
    vision: bool | None = None
    audio: bool | None = None
    user_vision: bool | None = None
    user_audio: bool | None = None
    video: bool | None = None
    """视频(读视频)在 tool 消息中的支持状态。"""
    user_video: bool | None = None
    """视频(读视频)在 user 消息中的支持状态。"""


# ---------------------------------------------------------------------------
# LLM Profile Types
# ---------------------------------------------------------------------------

class LLMProfile(BaseModel):
    """LLM 主模型配置项（前端可切换）。"""
    name: str = ""
    llm_client_name: str = ""
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    temperature: float = 0.7
    max_output_tokens: int = 4096
    reasoning_effort: str = ""
    max_context_tokens: int = 128000
    # 多模态分工直接引用根对象中的 LLMProfile 实例。
    vision_image_profile: LLMProfile | None = None
    audio_profile: LLMProfile | None = None
    vision_video_profile: LLMProfile | None = None


LLMProfile.model_rebuild()


class LLMProfileData(BaseModel):
    """LLMProfile 持久化根对象。"""

    profiles: list[LLMProfile] = Field(default_factory=list, description="LLMProfile列表")
    approval_profile: LLMProfile|None = Field(default=None)


class LLMProfilePayload(BaseModel):
    """HTTP 传输用的扁平 Profile，不包含 UID 或嵌套对象。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    llm_client_name: str
    base_url: str
    model: str
    api_key: str
    temperature: float
    max_output_tokens: int
    reasoning_effort: str
    max_context_tokens: int
    vision_image_profile: str | None
    audio_profile: str | None
    vision_video_profile: str | None


class LLMProfileUpdateRequest(BaseModel):
    """HTTP 单 Profile 更新请求。"""

    model_config = ConfigDict(extra="forbid")

    profile_name: str
    profile: LLMProfilePayload


class LLMProfileDeleteRequest(BaseModel):
    """HTTP Profile 删除请求；替换名称为 None 表示清空配置。"""

    model_config = ConfigDict(extra="forbid")

    profile_name: str
    replacement_profile_name: str | None


class LLMProfileMutationResponse(BaseModel):
    """HTTP Profile 创建/更新响应。"""

    model_config = ConfigDict(extra="forbid")

    profile: LLMProfilePayload
    notification_failures: list[str] = Field(default_factory=list)


class LLMProfileDeleteResult(BaseModel):
    """HTTP Profile 删除及会话替换结果。"""

    model_config = ConfigDict(extra="forbid")

    deleted: bool
    profile_name: str
    replacement_profile_name: str | None
    switched_sessions: list[str] = Field(default_factory=list)
    pending_sessions: list[str] = Field(default_factory=list)
    notification_failures: list[str] = Field(default_factory=list)