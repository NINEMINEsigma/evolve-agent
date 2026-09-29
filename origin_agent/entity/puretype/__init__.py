"""
puretype 包 — 只含有不包含任何方法定义的类型定义。

原始单文件 puretype.py 拆分为以下子模块：
    _base       : MessageContent, Role, ToolDangerLevel, ToolAvailability
    approval    : ApprovalMode, SessionApprovalModeState, ApprovalPolicy, ApprovalOutcome,
                  ApprovalResult, ApprovalProfileUpdateRequest, ApprovalProfileState,
                  ApprovalProfileMutationResponse, ToolCallMeta, ToolAllowlistEntry
    metadata    : MetadataProfileUpdateRequest, MetadataProfileState, MetadataProfileMutationResponse
    llm         : ToolCallRequest, Usage, MessageMetrics, LLMResponse, ToolCallDeltaPhase,
                  ToolCallDelta, StreamChunk, LLMProfile, LLMProfileData, LLMProfilePayload,
                  LLMProfileUpdateRequest, LLMProfileDeleteRequest, LLMProfileMutationResponse,
                  LLMProfileDeleteResult, ModalityCapability
    skills      : SkillPayload, SkillInfo
    session     : Loop, SessionStatus, LoopMeta, SessionInfo, SessionTerminationResult,
                  History skeleton/page/resource DTO, SessionMessageEntry, TokenUsageRecord, QueuedMessage
    agent       : AgentConfig
    ws          : MessageType, Message, HistoryRowLink, ClientDiagnosticKind,
                  ClientDiagnosticPhase, ClientDiagnostic
    lsp         : LSPState, LSPDiagnostic, LSPReference, LSPDefinition, LSPSymbol
    runtime     : SystemInfo, ClientInfo, ProcessLineStreamResult
    shell       : ShellInfo, ShellOutputSlice
    sandbox     : DynamicSandboxSpace, DynamicSandboxSpaceData
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
    ApprovalMode,
    SessionApprovalModeState,
    ApprovalPolicy,
    ApprovalOutcome,
    ApprovalResult,
    ApprovalProfileUpdateRequest,
    ApprovalProfileState,
    ApprovalProfileMutationResponse,
    ToolCallMeta,
    ToolAllowlistEntry,
)
from .metadata import (
    MetadataProfileUpdateRequest,
    MetadataProfileState,
    MetadataProfileMutationResponse,
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
    SessionLlmProfileState,
    ModalityCapability,
)
from .skills import (
    SkillPayload,
    SkillInfo,
)
from .session_visual import (
    SessionVisualKind,
    SessionVisualStatus,
    SessionVisualSource,
    SessionVisualResourceState,
    SessionVisualResources,
)
from .session import (
    Loop,
    SessionStatus,
    MainSessionActivitySource,
    MainSessionActivityPhase,
    MainSessionActivitySnapshot,
    SessionRuntimeStatus,
    LoopMeta,
    SessionInfo,
    SessionTerminationResult,
    SessionHistoryRowKind,
    SessionHistoryToolCardStatus,
    SessionHistoryToolCard,
    SessionHistorySkeletonRow,
    SessionHistorySkeletonResponse,
    SessionHistoryContentRow,
    SessionHistoryPageResponse,
    SessionHistoryImageResource,
    SessionHistoryDownloadResource,
    SessionHistoryResourcesResponse,
    SessionMessageEntry,
    TokenUsageRecord,
    QueuedMessage,
    MainSessionInterruptResult,
)
from .agent import (
    AgentConfig,
    CharacterProfile,
)
from .ws import (
    MessageType,
    Message,
    HistoryRowLink,
    ClientDiagnosticKind,
    ClientDiagnosticPhase,
    ClientDiagnostic,
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
    ProcessLineStreamResult,
)
from .shell import (
    ShellInfo,
    ShellOutputSlice,
)
from .sandbox import (
    DynamicSandboxSpace,
    DynamicSandboxSpaceData,
)
from .sandbox_spaces import (
    DynamicSandboxSpaceCreateRequest,
    DynamicSandboxSpaceUpdateRequest,
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
    "SessionVisualKind",
    "SessionVisualStatus",
    "SessionVisualSource",
    "SessionVisualResourceState",
    "SessionVisualResources",
    # _base
    "MessageContent",
    "Role",
    "ToolDangerLevel",
    "ToolAvailability",
    # approval
    "ApprovalMode",
    "SessionApprovalModeState",
    "ApprovalPolicy",
    "ApprovalOutcome",
    "ApprovalResult",
    "ApprovalProfileUpdateRequest",
    "ApprovalProfileState",
    "ApprovalProfileMutationResponse",
    "MetadataProfileUpdateRequest",
    "MetadataProfileState",
    "MetadataProfileMutationResponse",
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
    "SessionLlmProfileState",
    "ModalityCapability",
    # skills
    "SkillPayload",
    "SkillInfo",
    # session
    "Loop",
    "SessionStatus",
    "MainSessionActivitySource",
    "MainSessionActivityPhase",
    "MainSessionActivitySnapshot",
    "SessionRuntimeStatus",
    "LoopMeta",
    "SessionInfo",
    "SessionTerminationResult",
    "SessionHistoryRowKind",
    "SessionHistoryToolCardStatus",
    "SessionHistoryToolCard",
    "SessionHistorySkeletonRow",
    "SessionHistorySkeletonResponse",
    "SessionHistoryContentRow",
    "SessionHistoryPageResponse",
    "SessionHistoryImageResource",
    "SessionHistoryDownloadResource",
    "SessionHistoryResourcesResponse",
    "SessionMessageEntry",
    "TokenUsageRecord",
    "QueuedMessage",
    "MainSessionInterruptResult",
    # agent
    "AgentConfig",
    "CharacterProfile",
    # ws
    "MessageType",
    "Message",
    "HistoryRowLink",
    # lsp
    "LSPState",
    "LSPDiagnostic",
    "LSPReference",
    "LSPDefinition",
    "LSPSymbol",
    # runtime
    "SystemInfo",
    "ClientInfo",
    "ProcessLineStreamResult",
    # shell
    "ShellInfo",
    "ShellOutputSlice",
    # sandbox
    "DynamicSandboxSpace",
    "DynamicSandboxSpaceData",
    "DynamicSandboxSpaceCreateRequest",
    "DynamicSandboxSpaceUpdateRequest",
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