from pydantic import BaseModel, ConfigDict, Field


class MetadataProfileUpdateRequest(BaseModel):
    """项目级全局元数据 Profile 名称指针更新请求。"""

    model_config = ConfigDict(extra="forbid")

    profile_name: str | None


class MetadataProfileState(BaseModel):
    """项目级全局元数据 Profile 的服务端权威状态。"""

    profile_name: str | None = None
    model: str | None = None
    available: bool = False


class MetadataProfileMutationResponse(BaseModel):
    """全局元数据 Profile 更新响应。"""

    model_config = ConfigDict(extra="forbid")

    state: MetadataProfileState
    notification_failures: list[str] = Field(default_factory=list)
