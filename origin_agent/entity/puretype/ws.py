from enum import Enum
from pydantic import BaseModel, ConfigDict, Field
from typing import Annotated, Any, Literal

from .agentspace import AgentspaceEvent
from .llm import MessageMetrics, ToolCallDelta, ToolCallRequest

class ConfirmResponseRequest(BaseModel):
    """HTTP 审批确认响应请求。"""

    model_config = ConfigDict(extra="forbid")

    action: str = "deny"
    deny_reason: str | None = None
    denied_by: str = "user"


class AskAnswerItem(BaseModel):
    """Ask 单题回答：选项值数组 + 可选自定义文本（可与选项并存）。"""

    model_config = ConfigDict(extra="forbid")

    selected: list[str] = []
    custom_text: str | None = None


class AskResponseRequest(BaseModel):
    """HTTP Ask 回答请求：answers 顺序与提问的问题顺序一一对应；null 表示整表跳过。"""

    model_config = ConfigDict(extra="forbid")

    answers: list[AskAnswerItem] | None = None


# ---------------------------------------------------------------------------
# WebSocket Message Types
# ---------------------------------------------------------------------------

class MessageType(str, Enum):
    """WebSocket 消息类型枚举。"""

    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    CONFIRM_REQUEST = "confirm_request"
    CONFIRM_RESPONSE = "confirm_response"
    ASK_REQUEST = "ask_request"
    ASK_RESPONSE = "ask_response"
    INTERRUPT = "interrupt"
    DISGUST = "disgust"          # 厌恶信号，不中断 LLM 生成，拦截工具调用
    ERROR = "error"
    SYSTEM = "system"
    FILE_UPLOAD = "file_upload"
    HANDSFREE_MODE = "handsfree_mode"
    TASK_PROGRESS = "task_progress"
    CLIPBOARD_DISPLAY = "clipboard_display"
    STREAM_DELTA = "stream_delta"
    STREAM_DONE = "stream_done"
    PING = "ping"
    PONG = "pong"
    SUBAGENT_UPDATE = "subagent_update"
    HISTORY_SYNC = "history_sync"
    LLM_PROFILE_CHANGED = "llm_profile_changed"
    APPROVAL_PROFILE_CHANGED = "approval_profile_changed"
    METADATA_PROFILE_CHANGED = "metadata_profile_changed"
    MODALITY_PROFILE_CHANGED = "modality_profile_changed"
    AGENTSPACE_EVENT = "agentspace_event"
    CLIENT_DIAGNOSTIC = "client_diagnostic"


class StreamDeltaEvent(BaseModel):
    """流式增量事件；工具载荷保持模型类型，在 WebSocket 边界统一序列化。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    type: Literal[MessageType.STREAM_DELTA] = MessageType.STREAM_DELTA
    session_id: str = Field(min_length=1)
    stream_id: str = Field(min_length=1)
    delta: str | None = None
    reasoning_delta: str | None = None
    character_name: str | None = None
    tool_call: ToolCallRequest | None = None
    tool_call_delta: ToolCallDelta | None = None


class StreamDoneEvent(BaseModel):
    """流结束事件；content 缺失保留累计正文，显式空字符串表示空正文。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    type: Literal[MessageType.STREAM_DONE] = MessageType.STREAM_DONE
    session_id: str = Field(min_length=1)
    stream_id: str = Field(min_length=1)
    finish_reason: str
    content: str | None = None
    metrics: MessageMetrics | None = None


StreamEvent = Annotated[StreamDeltaEvent | StreamDoneEvent, Field(discriminator="type")]


class ClientDiagnosticKind(str, Enum):
    """客户端传输诊断类型。"""

    CRITICAL_REQUEST_TIMEOUT = "critical_request_timeout"


class ClientDiagnosticPhase(str, Enum):
    """客户端关键请求诊断阶段。"""

    SESSION_STATUS_PRECHECK = "session_status_precheck"
    SESSION_STATUS_RECHECK = "session_status_recheck"
    HISTORY_SKELETON = "history_skeleton"
    HISTORY_PAGE = "history_page"


class ClientDiagnostic(BaseModel):
    """不进入聊天 History 的脱敏客户端传输诊断。"""

    kind: ClientDiagnosticKind
    phase: ClientDiagnosticPhase
    duration_ms: int = Field(ge=0)
    websocket_state: str
    last_recv_age_ms: int | None = Field(default=None, ge=0)
    last_pong_age_ms: int | None = Field(default=None, ge=0)


class HistoryRowLink(BaseModel):
    """实时聊天行到正典 History 投影行的非持久化关联。"""

    live_id: str
    history_row_id: str


class Message(BaseModel):
    """通用 WebSocket 消息兼容模型。

    下行 stream_delta / stream_done 必须使用上方具体事件模型；此处保留
    既有入站及非流式协议字段，不作为流式发送入口。
    """

    type: MessageType
    session_id: str = ""
    content: Any | None = None
    tool: str | None = None
    args: dict[str, Any] | None = None
    result: Any | None = None
    message: str | None = None  # ERROR 类型使用
    request_id: str | None = None  # confirm_request / confirm_response 使用
    action: str | None = None      # confirm_response：allow_once | allow_always | deny
    deny_reason: str | None = None  # confirm_response：拒绝原因
    denied_by: str | None = None    # confirm_response：拒绝来源 (model/user/system)
    filename: str | None = None    # FILE_UPLOAD：原始文件名
    mime_type: str | None = None   # FILE_UPLOAD：MIME 类型
    file_data: str | None = None   # FILE_UPLOAD：base64 编码的文件内容
    local_path: str | None = None  # FILE_UPLOAD：本地文件路径（同盘时优先硬链接）
    # ask_request / ask_response 相关字段
    questions: list[dict[str, Any]] | None = None  # ASK_REQUEST：问题列表 [{question, detail, options, multi_select}]
    answers: list[dict[str, Any]] | None = None     # ASK_RESPONSE：按题回答列表 [{selected: [value], custom_text}]，顺序与 questions 对应
    # stream 相关字段
    stream_id: str | None = None   # STREAM_DELTA / STREAM_DONE：流标识
    delta: str | None = None       # STREAM_DELTA：文本增量
    reasoning_delta: str | None = None  # STREAM_DELTA：reasoning 增量
    finish_reason: str | None = None    # STREAM_DONE：结束原因或错误
    target_sessions: list[str] | None = None  # USER_MESSAGE：目标会话列表
    # 多 Agent 模式：用户消息的可见性和响应指定
    visible_characters: list[str] | None = None   # USER_MESSAGE：可见角色列表
    response_characters: list[str] | None = None  # USER_MESSAGE：需响应角色列表
    # tool_call / tool_result / confirm_request 相关字段
    tool_call_id: str | None = None  # TOOL_CALL / TOOL_RESULT：工具调用 ID
    character_name: str | None = None  # 消息发送者角色名
    index: int | None = None  # 消息在持久化历史中的索引
    is_system_status: bool | None = None  # SYSTEM：是否为已持久化的系统状态消息
    client_message_id: str | None = None  # 前端生成的乐观消息 ID，用于回显去重
    message_suffix: str | None = None  # 用户消息固定后缀（如 fixator 上下文）
    dynamic_message_suffix: str | None = None  # 用户消息动态后缀（如 memory/hooks 上下文）
    tool_call_meta: dict[str, Any] | None = None  # TOOL_RESULT：工具调用时间元信息
    embedded_messages: list[dict[str, Any]] | None = None  # TOOL_RESULT：工具结果中隐藏字段的嵌入消息
    consumed_client_message_ids: list[str] | None = None  # TOOL_RESULT：被工具链消费的用户消息 client_message_id 列表（前端用于移除已排队徽章）
    danger_level: str | None = None  # CONFIRM_REQUEST：工具危险等级
    client_info: dict[str, Any] | None = None  # USER_MESSAGE：前端携带的客户端信息
    # USER_MESSAGE/重新生成：前端当前选择的 Profile 名称；空字符串表示无配置。
    llm_profile_name: str | None = None
    # LLM_PROFILE_CHANGED：Profile 名称变更或删除的全局通知。
    operation: str | None = None
    old_name: str | None = None
    new_name: str | None = None
    metrics: MessageMetrics | None = None  # STREAM_DONE：计时元信息
    # HISTORY_SYNC：正典历史同步元数据（正文由 REST 按需读取）
    history_count: int | None = None
    processing: bool | None = None
    token_usage: int | None = None
    context_tokens: int | None = None
    agents: list[str] | None = None
    # APPROVAL_PROFILE_CHANGED：审批 Profile 状态变更通知
    approval_profile_name: str | None = None
    approval_profile_model: str | None = None
    approval_profile_available: bool | None = None
    # METADATA_PROFILE_CHANGED：全局元数据 Profile 状态变更通知
    metadata_profile_name: str | None = None
    metadata_profile_model: str | None = None
    metadata_profile_available: bool | None = None
    # MODALITY_PROFILE_CHANGED：全局多模态回退 Profile 状态
    modality_vision_image_profile_name: str | None = None
    modality_vision_image_profile_model: str | None = None
    modality_vision_image_profile_available: bool | None = None
    modality_audio_profile_name: str | None = None
    modality_audio_profile_model: str | None = None
    modality_audio_profile_available: bool | None = None
    modality_vision_video_profile_name: str | None = None
    modality_vision_video_profile_model: str | None = None
    modality_vision_video_profile_available: bool | None = None
    # HANDSFREE_MODE：服务端权威脱手模式回执
    handsfree_mode: bool | None = None
    # HANDSFREE_MODE：服务端权威审批模式（manual/handsfree/yolo）
    approval_mode: str | None = None
    # AGENTSPACE_EVENT：聊天页复用 WebSocket 接收的 Agentspace 事件。
    agentspace_event: AgentspaceEvent | None = None
    # CLIENT_DIAGNOSTIC：不进入聊天 History 的脱敏客户端传输诊断。
    client_diagnostic: ClientDiagnostic | None = None