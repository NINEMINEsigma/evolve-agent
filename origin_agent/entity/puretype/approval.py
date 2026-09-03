from pydantic import BaseModel, ConfigDict, Field

from entity.constant import SYSTEM_CHARACTER_NAME
from ._base import ToolDangerLevel

# ---------------------------------------------------------------------------
# Approval Types
# ---------------------------------------------------------------------------

class ApprovalPolicy(BaseModel):
    """审批策略：定义在特定会话角色下，哪些 danger_level 需要审批。

    主会话与子会话的差异在于审批来源：主会话直接由用户/脱手模型审批，
    子会话的工具审批由主 agent 代为审批，因此子会话采用更严格的阈值。

    normal_requires    : 正常模式下需要审批的 danger_level 集合。
    handsfree_requires : 脱手模式下需要审批的 danger_level 集合。
    """

    normal_requires: set[ToolDangerLevel]
    handsfree_requires: set[ToolDangerLevel]


class ApprovalOutcome(BaseModel):
    """
    审批流程的最终结果。
    """
    denied: bool = False
    """
    审批结果为 deny
    """
    deny_result: dict | None = None
    """
    deny 时的错误 dict，包含 error/denied/denied_by 字段
    """
    approved_args: dict = Field(default_factory=dict, description="审批通过后的 args 引用（已原地设置 _pre_approved / _approval_action）")


class ApprovalResult(BaseModel):
    """
    单次审批结果。与 ApprovalOutcome 不同，此类型直接对应审批后的 action 决策。
    """
    action: str
    """
    "allow_once" | "allow_always" | "deny"
    """
    deny_reason: str | None = None
    """
    拒绝原因，仅 action == "deny" 时有效
    """
    denied_by: str = SYSTEM_CHARACTER_NAME
    """
    拒绝来源："model"（脱手模式LLM）、"user"（人工）、"parent_agent"（父Agent）或 SYSTEM_CHARACTER_NAME（系统故障）
    """


class ApprovalProfileUpdateRequest(BaseModel):
    """项目级审批 Profile 名称指针更新请求。"""

    model_config = ConfigDict(extra="forbid")

    profile_name: str | None


class ApprovalProfileState(BaseModel):
    """项目级审批 Profile 的服务端权威状态。"""

    profile_name: str | None = None
    model: str | None = None
    available: bool = False


class ApprovalProfileMutationResponse(BaseModel):
    """审批 Profile 更新及联动结果。"""

    state: ApprovalProfileState
    disabled_sessions: list[str] = Field(default_factory=list)
    notification_failures: list[str] = Field(default_factory=list)


class ToolCallMeta(BaseModel):
    """工具调用的时间元信息。

    在 ToolExecutor 中自动收集并注入到工具返回结果的 ``_meta`` 字段。
    ``application_time`` 为人类可读的本地时间字符串，精确到毫秒；
    其余字段均为相对于 ``application_time_ms`` 的毫秒偏移。
    """
    application_time: str
    """人类可读的申请时间，格式 ``YYYY-MM-DD HH:MM:SS.mmm``。"""
    application_time_ms: int
    """申请时间的绝对毫秒时间戳，供机器计算使用。"""
    approval_duration_ms: int
    """审批耗时（毫秒），safe 工具为 0。"""
    invocation_start_offset_ms: int
    """从申请到开始调用 handler 的毫秒偏移。"""
    invocation_duration_ms: int
    """handler 实际执行的毫秒数。"""
    end_time_offset_ms: int
    """从申请到工具调用完成的毫秒偏移。"""


class ToolAllowlistEntry(BaseModel):
    """
    工具 allowlist 中的单条永久授权记录。
    """
    tool: str
    """
    工具名称
    """
    args: dict = Field(default_factory=dict)
    """
    标准化的工具参数字典（已排除内部标记字段）
    """