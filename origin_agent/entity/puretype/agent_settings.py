"""全局工具循环配置的消息前纯类型。"""

from pydantic import BaseModel, ConfigDict, Field

from entity.constant import MAX_CONFIGURABLE_TOOL_TURNS, MIN_TOOL_TURNS


class AgentLoopSettingsData(BaseModel):
    """独立持久化根；None表示使用当前默认常量。"""

    # easysave还原时逐字段赋值，持久化根不能冻结；仅Store持有该根。
    model_config = ConfigDict(extra="forbid", strict=True)

    max_tool_turns: int | None = Field(
        default=None, ge=MIN_TOOL_TURNS, le=MAX_CONFIGURABLE_TOOL_TURNS,
    )


class AgentLoopSettingsUpdateRequest(BaseModel):
    """必须明确提交配置值或None，不将缺字段当作恢复默认。"""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    max_tool_turns: int | None = Field(
        ge=MIN_TOOL_TURNS, le=MAX_CONFIGURABLE_TOOL_TURNS,
    )


class AgentLoopSettingsState(BaseModel):
    """服务端权威配置值、当前有效值与默认值。"""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    max_tool_turns: int | None = Field(
        ge=MIN_TOOL_TURNS, le=MAX_CONFIGURABLE_TOOL_TURNS,
    )
    effective_max_tool_turns: int = Field(
        ge=MIN_TOOL_TURNS, le=MAX_CONFIGURABLE_TOOL_TURNS,
    )
    default_max_tool_turns: int = Field(
        ge=MIN_TOOL_TURNS, le=MAX_CONFIGURABLE_TOOL_TURNS,
    )
