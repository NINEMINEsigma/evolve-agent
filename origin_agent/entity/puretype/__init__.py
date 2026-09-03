"""
puretype 包 — 只含有不包含任何方法定义的类型定义。

原始单文件 puretype.py 拆分为以下子模块：
    _base       : MessageContent, Role, ToolDangerLevel, ToolAvailability
    approval    : ApprovalPolicy, ApprovalOutcome, ApprovalResult, ApprovalProfileUpdateRequest,
                  ApprovalProfileState, ApprovalProfileMutationResponse, ToolCallMeta, ToolAllowlistEntry
    llm         : ToolCallRequest, Usage, MessageMetrics, LLMResponse, ToolCallDeltaPhase,
                  ToolCallDelta, StreamChunk, LLMProfile, LLMProfileData, LLMProfilePayload,
                  LLMProfileUpdateRequest, LLMProfileDeleteRequest, LLMProfileMutationResponse,
                  LLMProfileDeleteResult, ModalityCapability
    skills      : SkillPayload, SkillInfo
    session     : Loop, SessionStatus, LoopMeta, SessionInfo, SessionMessageEntry, TokenUsageRecord, QueuedMessage
    agent       : AgentConfig
    ws          : MessageType, Message
    lsp         : LSPState, LSPDiagnostic, LSPReference, LSPDefinition, LSPSymbol
    runtime     : SystemInfo, ClientInfo
    extools     : CronTaskInfo, DynamicEndpointInfo
    agentspace  : AgentspaceEntry/Event/FileSnapshot/Lock/Trash 与 REST 请求模型

所有公共名称通过 __init__.py 再导出，保持 ``from entity.puretype import X`` 的向后兼容。
"""

from ._base import (
    MessageContent,
    Role,
    ToolDangerLevel,
    ToolAvailability,
)
from .approval import (
    ApprovalPolicy,
    ApprovalOutcome,
    ApprovalResult,
    ApprovalProfileUpdateRequest,
    ApprovalProfileState,
    ApprovalProfileMutationResponse,
    ToolCallMeta,
    ToolAllowlistEntry,
)
from .llm import (
    ToolCallRequest,
    Usage,
    MessageMetrics,
    LLMResponse,
    ToolCallDeltaPhase,
    ToolCallDelta,
    StreamChunk,
    LLMProfile,
    LLMProfileData,
    LLMProfilePayload,
    LLMProfileUpdateRequest,
    LLMProfileDeleteRequest,
    LLMProfileMutationResponse,
    LLMProfileDeleteResult,
    ModalityCapability,
)
from .skills import (
    SkillPayload,
    SkillInfo,
)
from .session import (
    Loop,
    SessionStatus,
    LoopMeta,
    SessionInfo,
    SessionMessageEntry,
    TokenUsageRecord,
    QueuedMessage,
)
from .agent import (
    AgentConfig,
)
from .ws import (
    MessageType,
    Message,
)
from .lsp import (
    LSPState,
    LSPDiagnostic,
    LSPReference,
    LSPDefinition,
    LSPSymbol,
)
from .runtime import (
    SystemInfo,
    ClientInfo,
)
from .extools import (
    CronTaskInfo,
    DynamicEndpointInfo,
)
from .agentspace import (
    AgentspaceEntryKind,
    AgentspaceEventKind,
    AgentspaceEventSource,
    AgentspaceTrashState,
    AgentspaceEntry,
    AgentspacePathIdentity,
    AgentspaceFileSnapshot,
    AgentspaceLockOwner,
    AgentspaceLockInfo,
    AgentspaceEvent,
    AgentspaceTrashEntry,
    AgentspaceWriteRequest,
    AgentspacePathRequest,
    AgentspaceRenameRequest,
)

__all__ = [
    # _base
    "MessageContent",
    "Role",
    "ToolDangerLevel",
    "ToolAvailability",
    # approval
    "ApprovalPolicy",
    "ApprovalOutcome",
    "ApprovalResult",
    "ApprovalProfileUpdateRequest",
    "ApprovalProfileState",
    "ApprovalProfileMutationResponse",
    "ToolCallMeta",
    "ToolAllowlistEntry",
    # llm
    "ToolCallRequest",
    "Usage",
    "MessageMetrics",
    "LLMResponse",
    "ToolCallDeltaPhase",
    "ToolCallDelta",
    "StreamChunk",
    "LLMProfile",
    "LLMProfileData",
    "LLMProfilePayload",
    "LLMProfileUpdateRequest",
    "LLMProfileDeleteRequest",
    "LLMProfileMutationResponse",
    "LLMProfileDeleteResult",
    "ModalityCapability",
    # skills
    "SkillPayload",
    "SkillInfo",
    # session
    "Loop",
    "SessionStatus",
    "LoopMeta",
    "SessionInfo",
    "SessionMessageEntry",
    "TokenUsageRecord",
    "QueuedMessage",
    # agent
    "AgentConfig",
    # ws
    "MessageType",
    "Message",
    # lsp
    "LSPState",
    "LSPDiagnostic",
    "LSPReference",
    "LSPDefinition",
    "LSPSymbol",
    # runtime
    "SystemInfo",
    "ClientInfo",
    # extools
    "CronTaskInfo",
    "DynamicEndpointInfo",
    # agentspace
    "AgentspaceEntryKind",
    "AgentspaceEventKind",
    "AgentspaceEventSource",
    "AgentspaceTrashState",
    "AgentspaceEntry",
    "AgentspacePathIdentity",
    "AgentspaceFileSnapshot",
    "AgentspaceLockOwner",
    "AgentspaceLockInfo",
    "AgentspaceEvent",
    "AgentspaceTrashEntry",
    "AgentspaceWriteRequest",
    "AgentspacePathRequest",
    "AgentspaceRenameRequest",
]