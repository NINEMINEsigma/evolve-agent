from enum import Enum
from pydantic import BaseModel
from typing import Any

from .llm import MessageMetrics

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
    LLM_PROFILE_CHANGED = "llm_profile_changed"


class Message(BaseModel):
    """WebSocket 消息模型。"""

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
    question: str | None = None    # ASK_REQUEST：问题文本
    options: list | None = None    # ASK_REQUEST：选项列表 [{label, value}]
    option: str | None = None      # ASK_RESPONSE：选中的选项值
    custom_text: str | None = None # ASK_RESPONSE：自定义输入文本
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
    client_message_id: str | None = None  # 前端生成的乐观消息 ID，用于回显去重
    message_suffix: str | None = None  # 用户消息固定后缀（如 fixator 上下文）
    dynamic_message_suffix: str | None = None  # 用户消息动态后缀（如 memory/hooks 上下文）
    tool_call_meta: dict[str, Any] | None = None  # TOOL_RESULT：工具调用时间元信息
    emoji: str | None = None  # 工具调用/审批请求的图标
    danger_level: str | None = None  # CONFIRM_REQUEST：工具危险等级
    client_info: dict[str, Any] | None = None  # USER_MESSAGE：前端携带的客户端信息
    # USER_MESSAGE/重新生成：前端当前选择的 Profile 名称；空字符串表示无配置。
    llm_profile_name: str | None = None
    # LLM_PROFILE_CHANGED：Profile 名称变更或删除的全局通知。
    operation: str | None = None
    old_name: str | None = None
    new_name: str | None = None
    metrics: MessageMetrics | None = None  # STREAM_DONE：计时元信息