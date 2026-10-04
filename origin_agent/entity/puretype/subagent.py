"""子Agent编排边界使用的稳定数据类型。"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SubAgentStatus(str, Enum):
    """子Agent及临时Agent的运行状态。"""

    running = "running"
    waiting = "waiting"
    completed = "completed"
    terminated = "terminated"


class SubAgentFeedback(BaseModel):
    """子Agent反馈或前端面板事件。"""

    role: str
    content: str = ""
    tool_name: str | None = None
    tool_call_id: str | None = None
    tool_args: dict[str, Any] | None = None
    reasoning: str | None = None
    character_name: str | None = None


class SubAgentPendingApproval(BaseModel):
    """子Agent等待父Agent审批的工具调用。"""

    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class SubAgentApprovalDecisionResult(BaseModel):
    """单项子Agent工具审批的处理结果。"""

    tool_call_id: str
    approved: bool
    reason: str | None = None


class SubAgentPromotion(BaseModel):
    """从等待队列晋升为活跃状态的子Agent。"""

    session_id: str
    subagent_name: str


class SubAgentLaunchResult(BaseModel):
    """启动普通子Agent或临时Agent的结果。"""

    success: bool
    session_id: str | None = None
    waiting: bool = False
    queue_position: int | None = None
    error: str | None = None


class SubAgentChatResult(BaseModel):
    """向普通子Agent发送消息的结果。"""

    success: bool
    session_id: str
    feedback: list[str] = Field(default_factory=list)
    note: str | None = None
    error: str | None = None


class SubAgentApprovalResult(BaseModel):
    """批量处理子Agent工具审批的结果。"""

    success: bool
    session_id: str
    processed: int = 0
    results: list[SubAgentApprovalDecisionResult] = Field(default_factory=list)
    feedback: list[str] = Field(default_factory=list)
    error: str | None = None


class SubAgentStopResult(BaseModel):
    """停止普通子Agent或临时Agent的结果。"""

    success: bool
    session_id: str
    session_path: str | None = None
    promoted: list[SubAgentPromotion] = Field(default_factory=list)
    note: str | None = None
    error: str | None = None


class SubAgentSnapshot(BaseModel):
    """单个活跃子Agent的完整运行快照。"""

    session_id: str
    name: str
    status: SubAgentStatus
    feedback: list[SubAgentFeedback] = Field(default_factory=list)
    pending_approvals: list[SubAgentPendingApproval] = Field(default_factory=list)
    interactive: bool = True


class SubAgentSnapshotResponse(BaseModel):
    """指定主会话下的子Agent快照集合。"""

    session_id: str
    subagents: dict[str, SubAgentSnapshot] = Field(default_factory=dict)


class SubAgentUpdate(BaseModel):
    """发送给前端的单次子Agent状态更新。"""

    session_id: str
    name: str
    status: SubAgentStatus
    feedback: list[SubAgentFeedback] = Field(default_factory=list)
    pending_approvals: list[SubAgentPendingApproval] = Field(default_factory=list)
    removed: bool = False
    interactive: bool = True
