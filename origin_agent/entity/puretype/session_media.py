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


class SessionMediaUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    send_multimodal: StrictBool
    expected_send_multimodal: StrictBool


class SessionMediaUpdateResponse(BaseModel):
    session_id: str
    item: SessionMediaItem
