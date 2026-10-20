"""Pre-message pure types, with no method definitions.

This package must not depend on entity.messages or entity.puretype_after,
including through TYPE_CHECKING imports. Types that require defined message
models belong in the sibling entity.puretype_after package, which exports them
independently. The message definition layer must not import that later package.

The original puretype.py module is split by responsibility:
    _base       : MessageContent, TypedMessageContent, ContentBlock, content block models, Role, ToolDangerLevel, ToolAvailability
    tool        : ToolBatchDecision
    approval    : ApprovalMode, SessionApprovalModeState, ApprovalPolicy, ApprovalOutcome,
                  ApprovalResult, ApprovalProfileUpdateRequest, ApprovalProfileState,
                  ApprovalProfileMutationResponse, ToolCallMeta, ToolAllowlistEntry
    metadata    : MetadataProfileUpdateRequest, MetadataProfileState, MetadataProfileMutationResponse
    modality    : ModalityType, ModalityProfileState, ModalityProfileUpdateRequest,
                  ModalityProfileMutationResponse, ModalityProfileStates
    llm         : ToolCallRequest, Usage, MessageMetrics, LLMResponse, ToolCallDeltaPhase,
                  ToolCallDelta, StreamChunk, LLMProfile, LLMProfileData, LLMProfilePayload,
                  LLMProfileUpdateRequest, LLMProfileDeleteRequest, LLMProfileMutationResponse,
                  LLMProfileDeleteResult, ModalityCapability
    skills      : SkillPayload, SkillInfo
    session     : Loop, SessionStatus, LoopMeta, SessionInfo, SessionRuntimeStatus,
                  SessionTabCapabilities, SessionTerminationResult,
                  SessionTagsUpdateRequest, SessionTitleUpdateRequest, SessionMessageEditRequest,
                  SessionRegenerateRequest, SessionMergeRequest,
                  SessionMessageEditResult, SessionMessageDeletionResult,
                  SessionRegenerateResult, SessionToolResources,
                  SessionRuntimeResourceTransferResult, SessionMergeResult,
                  History skeleton/page/resource DTO, SessionMessageEntry, TokenUsageRecord, QueuedMessage
    subagent    : SubAgentStatus, SubAgentFeedback, SubAgentPendingApproval,
                  SubAgentLaunchResult, SubAgentChatResult, SubAgentApprovalResult,
                  SubAgentStopResult, SubAgentSnapshot, SubAgentSnapshotResponse,
                  SubAgentUpdate
    agent       : AgentConfig
    ws          : MessageType, Message, ConfirmResponseRequest, AskResponseRequest,
                  StreamDeltaEvent, StreamDoneEvent, StreamEvent,
                  HistoryRowLink, ClientDiagnosticKind, ClientDiagnosticPhase, ClientDiagnostic
    lsp         : LSPState, LSPDiagnostic, LSPReference, LSPDefinition, LSPSymbol
    runtime     : SystemInfo, ClientInfo, ProcessLineStreamResult
    shell       : ShellInfo, ShellOutputSlice
    sandbox     : DynamicSandboxSpace, DynamicSandboxSpaceData
    extools     : CronTaskInfo, DynamicEndpointInfo, DynamicEndpointRequest
    agentspace  : AgentspaceEntry/Event/FileSnapshot/Lock/Trash 与 REST 请求模型

Retained public pre-message types are explicitly re-exported here, preserving
``from entity.puretype import X`` for those types only. Post-message types are
not re-exported here; import them from entity.puretype_after.
"""

from .session_file_changes import (
    SessionFileChangeActor, SessionFileChangeOperation, SessionFileChangeEntry,
    SessionFileChangesData, SessionFileChangesSummary, SessionFileChangesPage,
)
from .session_media import (
    SessionMediaItem,
    SessionMediaListResponse,
    SessionMediaUpdateRequest,
    SessionMediaUpdateResponse,
)
from .session_variables import (
    SessionVariableFileIdentity, SessionVariableDirectoryIdentity,
    SessionVariableMetadata, SessionVariableIssue, SessionVariableEntry,
    SessionVariablePoolResponse, SessionVariableSnapshotNode,
    SessionVariableSourceSnapshot, SessionVariableInheritanceData,
)
from ._base import (
    MessageContent,
    TypedMessageContent,
    ContentBlock,
    TextContentBlock,
    ImageURLContent,
    ImageContentBlock,
    AudioInputContent,
    AudioContentBlock,
    VideoURLContent,
    VideoContentBlock,
    Role,
    ToolDangerLevel,
    ToolAvailability,
)
from .tool import ToolBatchDecision
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
from .mcp import MCPBridgeCall, MCPOAuthProviderEntry
from .lifecycle import (
    ManagedTaskRecord,
    SyncToolCallRecord,
    InputDelivery,
    ShutdownInputReport,
    ToolResultNotification,
)
from .metadata import (
    MetadataProfileUpdateRequest,
    MetadataProfileState,
    MetadataProfileMutationResponse,
    ToolchainSummaryProfileUpdateRequest,
    ToolchainSummaryProfileState,
    ToolchainSummaryProfileMutationResponse,
)
from .modality import (
    ModalityDescriptionResult,
    ModalityType,
    ModalityProfileState,
    ModalityProfileUpdateRequest,
    ModalityProfileMutationResponse,
    ModalityProfileStates,
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
from .subagent import (
    SubAgentStatus,
    SubAgentFeedback,
    SubAgentFeedbackDelivery,
    SubAgentPendingApproval,
    SubAgentApprovalDecisionResult,
    SubAgentLaunchResult,
    SubAgentChatResult,
    SubAgentApprovalResult,
    SubAgentStopResult,
    SubAgentSnapshot,
    SubAgentSnapshotResponse,
    SubAgentUpdate,
)
from .session import (
    Loop,
    SessionStatus,
    MainSessionActivitySource,
    MainSessionActivityPhase,
    MainSessionActivitySnapshot,
    SessionRuntimeStatus,
    SessionTabCapabilities,
    LoopMeta,
    SessionInfo,
    SessionTerminationResult,
    SessionTagsUpdateRequest,
    SessionTitleUpdateRequest,
    SessionMessageEditRequest,
    SessionRegenerateRequest,
    SessionMergeRequest,
    SessionMessageEditResult,
    SessionMessageDeletionResult,
    SessionRegenerateResult,
    SessionToolResources,
    SessionRuntimeResourceTransferResult,
    SessionMergeResult,
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
    ToolChainSpan,
)
from .session_export import (
    SessionExportStamp, SessionExportHistorySnapshot, SessionExportVisualEntry,
    SessionExportLimits, SessionExportSnapshotResponse, SessionExportResourceSource,
    SessionExportResourceRequest, SessionExportResourceProof,
    SessionExportVerifyRequest, SessionExportVerifyResponse, SessionExportResourceIssue,
)
from .agent import (
    AgentConfig,
    CharacterProfile,
    CharacterAvatarEntry,
    CharacterAvatarsResponse,
    CharacterProfileEntry,
    CharacterProfilesResponse,
)
from .ws import (
    MessageType,
    Message,
    StreamDeltaEvent,
    StreamDoneEvent,
    StreamEvent,
    HistoryUpdatedEvent,
    HistoryRowLink,
    ClientDiagnosticKind,
    ClientDiagnosticPhase,
    ClientDiagnostic,
    ConfirmResponseRequest,
    AskAnswerItem,
    AskResponseRequest,
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
    DynamicEndpointRequest,
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
    AgentspaceOperationRequest,
    AgentspaceWriteRequest,
    AgentspacePathRequest,
    AgentspaceRenameRequest,
)

__all__ = [
    "SessionFileChangeActor", "SessionFileChangeOperation", "SessionFileChangeEntry",
    "SessionFileChangesData", "SessionFileChangesSummary", "SessionFileChangesPage",
    "SessionExportStamp", "SessionExportHistorySnapshot", "SessionExportVisualEntry",
    "SessionExportLimits", "SessionExportSnapshotResponse", "SessionExportResourceSource",
    "SessionExportResourceRequest", "SessionExportResourceProof",
    "SessionExportVerifyRequest", "SessionExportVerifyResponse", "SessionExportResourceIssue",
    "SessionMediaItem",
    "SessionMediaListResponse",
    "SessionMediaUpdateRequest",
    "SessionMediaUpdateResponse",
    "ModalityDescriptionResult",
    "SessionVariableFileIdentity", "SessionVariableDirectoryIdentity",
    "SessionVariableMetadata", "SessionVariableIssue", "SessionVariableEntry",
    "SessionVariablePoolResponse", "SessionVariableSnapshotNode",
    "SessionVariableSourceSnapshot", "SessionVariableInheritanceData",
    "MCPBridgeCall",
    "MCPOAuthProviderEntry",
    "ManagedTaskRecord",
    "SyncToolCallRecord",
    "InputDelivery",
    "ShutdownInputReport",
    "ToolResultNotification",
    "SubAgentFeedbackDelivery",
    "SessionVisualKind",
    "SessionVisualStatus",
    "SessionVisualSource",
    "SessionVisualResourceState",
    "SessionVisualResources",
    # _base
    "MessageContent",
    "TypedMessageContent",
    "ContentBlock",
    "TextContentBlock",
    "ImageURLContent",
    "ImageContentBlock",
    "AudioInputContent",
    "AudioContentBlock",
    "VideoURLContent",
    "VideoContentBlock",
    "Role",
    "ToolDangerLevel",
    "ToolAvailability",
    "ToolBatchDecision",
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
    "ToolchainSummaryProfileUpdateRequest",
    "ToolchainSummaryProfileState",
    "ToolchainSummaryProfileMutationResponse",
    # modality
    "ModalityType",
    "ModalityProfileState",
    "ModalityProfileUpdateRequest",
    "ModalityProfileMutationResponse",
    "ModalityProfileStates",
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
    # subagent
    "SubAgentStatus",
    "SubAgentFeedback",
    "SubAgentPendingApproval",
    "SubAgentApprovalDecisionResult",
    "SubAgentLaunchResult",
    "SubAgentChatResult",
    "SubAgentApprovalResult",
    "SubAgentStopResult",
    "SubAgentSnapshot",
    "SubAgentSnapshotResponse",
    "SubAgentUpdate",
    # session
    "Loop",
    "SessionStatus",
    "MainSessionActivitySource",
    "MainSessionActivityPhase",
    "MainSessionActivitySnapshot",
    "SessionRuntimeStatus",
    "SessionTabCapabilities",
    "LoopMeta",
    "SessionInfo",
    "SessionTerminationResult",
    "SessionTagsUpdateRequest",
    "SessionTitleUpdateRequest",
    "SessionMessageEditRequest",
    "SessionRegenerateRequest",
    "SessionMergeRequest",
    "SessionMessageEditResult",
    "SessionMessageDeletionResult",
    "SessionRegenerateResult",
    "SessionToolResources",
    "SessionRuntimeResourceTransferResult",
    "SessionMergeResult",
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
    "ToolChainSpan",
    # agent
    "AgentConfig",
    "CharacterProfile",
    "CharacterAvatarEntry",
    "CharacterAvatarsResponse",
    "CharacterProfileEntry",
    "CharacterProfilesResponse",
    # ws
    "MessageType",
    "Message",
    "StreamDeltaEvent",
    "StreamDoneEvent",
    "StreamEvent",
    "HistoryUpdatedEvent",
    "HistoryRowLink",
    "ConfirmResponseRequest",
    "AskAnswerItem",
    "AskResponseRequest",
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
    "DynamicEndpointRequest",
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
    "AgentspaceOperationRequest",
    "AgentspaceWriteRequest",
    "AgentspacePathRequest",
    "AgentspaceRenameRequest",
]