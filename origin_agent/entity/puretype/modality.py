from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ModalityType = Literal["image", "audio", "video"]


class ModalityProfileState(BaseModel):
    """单种媒体的全局回退 Profile 服务端状态。"""

    profile_name: str | None = None
    model: str | None = None
    available: bool = False


class ModalityProfileUpdateRequest(BaseModel):
    """单种媒体的全局回退 Profile 引用更新请求。"""

    model_config = ConfigDict(extra="forbid")

    media_type: ModalityType
    profile_name: str | None


class ModalityProfileMutationResponse(BaseModel):
    """单种媒体全局回退 Profile 更新响应。"""

    model_config = ConfigDict(extra="forbid")

    state: ModalityProfileState
    notification_failures: list[str] = Field(default_factory=list)


class ModalityProfileStates(BaseModel):
    """三种媒体的全局回退 Profile 状态快照。"""

    image: ModalityProfileState
    audio: ModalityProfileState
    video: ModalityProfileState
