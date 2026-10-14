"""主会话 History 媒体实例的轻量清单与开关协议。"""

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from ._base import Role
from .modality import ModalityType


class SessionMediaItem(BaseModel):
    media_id: str
    history_index: int
    block_index: int
    media_type: ModalityType
    role: Role
    character_name: str | None
    source_path: str | None
    tool_call_id: str | None
    send_multimodal: bool
    has_forward_description: bool
    mime_type: str | None
    inline_payload_chars: int | None
    preview_available: bool


class SessionMediaListResponse(BaseModel):
    session_id: str
    history_count: int
    total_count: int
    offset: int
    limit: int
    editable: bool
    items: list[SessionMediaItem] = Field(default_factory=list)
    # 全 History 媒体聚合（不随分页变化）：开启/关闭直接发送的实例数量。
    enabled_count: int = 0
    disabled_count: int = 0
    # 开启/关闭实例中 inline_payload_chars 非空值之和；字符数，非字节数。
    enabled_inline_payload_chars: int = 0
    disabled_inline_payload_chars: int = 0
    # 开启/关闭实例中 inline_payload_chars 为 None（远程/非内联）的数量。
    enabled_unknown_payload_count: int = 0
    disabled_unknown_payload_count: int = 0


class SessionMediaUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    send_multimodal: StrictBool
    expected_send_multimodal: StrictBool


class SessionMediaUpdateResponse(BaseModel):
    session_id: str
    item: SessionMediaItem
