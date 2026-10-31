"""Explicit, ordered endpoint component registration."""

from fastapi import APIRouter
from interface.api_component import APIComponent
from interface.gateway_system import IGatewaySystem

from .pages.index import IndexAPI
from .system.health import HealthAPI
from .activity.overview import ActivityOverviewAPI
from .activity.events import ActivityEventsAPI
from .sessions.list import ListSessionsAPI
from .sessions.list_tags import ListTagsAPI
from .sessions.update_tags import UpdateSessionTagsAPI
from .sessions.tool_resources import SessionToolResourcesAPI
from .sessions.file_changes_summary import SessionFileChangesSummaryAPI
from .sessions.file_changes import SessionFileChangesAPI
from .sessions.tab_capabilities import SessionTabCapabilitiesAPI
from .sessions.variables import SessionVariablesAPI
from .sessions.status import SessionStatusAPI
from .sessions.llm_profile import SessionLlmProfileAPI
from .characters.avatars import CharacterAvatarsAPI
from .characters.profiles import CharacterProfilesAPI
from .sessions.subagents import SessionSubagentsAPI
from .interactions.confirm import ConfirmResponseAPI
from .interactions.ask import AskResponseAPI
from .interactions.interrupt import InterruptSessionAPI
from .interactions.disgust import DisgustSessionAPI
from .sessions.delete import DeleteSessionAPI
from .session_export.snapshot import SessionExportSnapshotAPI
from .session_export.resource import SessionExportResourceAPI
from .session_export.verify import SessionExportVerifyAPI
from .session_export.viewer import SessionExportViewerAPI
from .history.skeleton import HistorySkeletonAPI
from .history.page import HistoryPageAPI
from .history.resources import HistoryResourcesAPI
from .history.media_list import HistoryMediaListAPI
from .history.media_update import HistoryMediaUpdateAPI
from .history.media_content import HistoryMediaContentAPI
from .history.message_edit import EditHistoryMessageAPI
from .history.messages_delete import DeleteHistoryMessagesAPI
from .history.message_delete import DeleteHistoryMessageAPI
from .history.regenerate import RegenerateResponseAPI
from .history.resume import ResumeSessionAPI
from .sessions.update_title import UpdateSessionTitleAPI
from .sessions.auto_title import AutoTitleSessionAPI
from .sessions.auto_tags import AutoTagsSessionAPI
from .sessions.regenerate_summary import RegenerateSessionSummaryAPI
from .sessions.terminate import TerminateSessionAPI
from .sessions.pin import PinSessionAPI
from .sessions.merge import MergeSessionsAPI
from .sessions.branch import BranchSessionAPI
from .shells.list import ListSessionShellsAPI
from .shells.stop import StopSessionShellAPI
from .cron.list import ListSessionCronTasksAPI
from .cron.trigger import TriggerSessionCronTaskAPI
from .cron.cancel import CancelSessionCronTaskAPI
from .dynamic.call import DynamicEndpointAPI
from .uploads.file_picker import FilePickerAPI
from .files.serve import ServeWorkspaceFileAPI
from .files.local_font import ServeLocalFontAPI
from .files.download import DownloadWorkspaceFileAPI
from .files.zip import DownloadDirectoryZipAPI
from .sandbox_spaces.list import ListSandboxSpacesAPI
from .sandbox_spaces.create import CreateSandboxSpaceAPI
from .sandbox_spaces.update import UpdateSandboxSpaceAPI
from .sandbox_spaces.delete import DeleteSandboxSpaceAPI
from .sandbox_spaces.pick_directory import PickSandboxDirectoryAPI
from .profiles.approval_get import GetApprovalProfileAPI
from .profiles.approval_update import UpdateApprovalProfileAPI
from .profiles.modality_get import GetModalityProfilesAPI
from .profiles.modality_update import UpdateModalityProfileAPI
from .system.agent_loop_settings_get import GetAgentLoopSettingsAPI
from .system.agent_loop_settings_update import UpdateAgentLoopSettingsAPI
from .profiles.metadata_get import GetMetadataProfileAPI
from .profiles.metadata_update import UpdateMetadataProfileAPI
from .profiles.toolchain_summary_get import GetToolchainSummaryProfileAPI
from .profiles.toolchain_summary_update import UpdateToolchainSummaryProfileAPI
from .agentspace.list import AgentspaceListAPI
from .agentspace.read import AgentspaceReadAPI
from .agentspace.write import AgentspaceWriteAPI
from .agentspace.mkdir import AgentspaceMkdirAPI
from .agentspace.rename import AgentspaceRenameAPI
from .agentspace.delete import AgentspaceDeleteAPI
from .agentspace.trash_list import AgentspaceTrashListAPI
from .agentspace.trash_restore import AgentspaceTrashRestoreAPI
from .agentspace.trash_purge import AgentspaceTrashPurgeAPI
from .agentspace.trash_empty import AgentspaceTrashEmptyAPI
from .agentspace.locks import AgentspaceLocksAPI
from .agentspace.events import AgentspaceEventsAPI
from .skills.list import ListSkillsAPI
from .profiles.clients import ListLlmClientsAPI
from .profiles.llm_list import ListLlmProfilesAPI
from .profiles.llm_create import CreateLlmProfileAPI
from .profiles.llm_update import UpdateLlmProfileAPI
from .profiles.llm_delete import DeleteLlmProfileAPI
from .pages.spa import SpaFallbackAPI
from .websocket.chat import ChatWebSocketAPI

# 声明顺序是协议匹配顺序，SPA兜底必须位于普通HTTP端点之后。
_API_COMPONENT_TYPES: tuple[type[APIComponent], ...] = (
    IndexAPI, HealthAPI, ActivityOverviewAPI, ActivityEventsAPI,
    ListSessionsAPI, ListTagsAPI, UpdateSessionTagsAPI, SessionToolResourcesAPI,
    SessionFileChangesSummaryAPI, SessionFileChangesAPI, SessionTabCapabilitiesAPI,
    SessionVariablesAPI, SessionStatusAPI, SessionLlmProfileAPI,
    CharacterAvatarsAPI, CharacterProfilesAPI, SessionSubagentsAPI,
    ConfirmResponseAPI, AskResponseAPI, InterruptSessionAPI, DisgustSessionAPI,
    DeleteSessionAPI, SessionExportSnapshotAPI, SessionExportResourceAPI,
    SessionExportVerifyAPI, SessionExportViewerAPI, HistorySkeletonAPI,
    HistoryPageAPI, HistoryResourcesAPI, HistoryMediaListAPI,
    HistoryMediaUpdateAPI, HistoryMediaContentAPI, EditHistoryMessageAPI,
    DeleteHistoryMessagesAPI, DeleteHistoryMessageAPI, RegenerateResponseAPI,
    ResumeSessionAPI, UpdateSessionTitleAPI, AutoTitleSessionAPI, AutoTagsSessionAPI,
    RegenerateSessionSummaryAPI, TerminateSessionAPI, PinSessionAPI,
    MergeSessionsAPI, BranchSessionAPI, ListSessionShellsAPI, StopSessionShellAPI,
    ListSessionCronTasksAPI, TriggerSessionCronTaskAPI, CancelSessionCronTaskAPI,
    DynamicEndpointAPI, FilePickerAPI, ServeWorkspaceFileAPI, ServeLocalFontAPI,
    DownloadWorkspaceFileAPI, DownloadDirectoryZipAPI, ListSandboxSpacesAPI,
    CreateSandboxSpaceAPI, UpdateSandboxSpaceAPI, DeleteSandboxSpaceAPI,
    PickSandboxDirectoryAPI, GetApprovalProfileAPI, UpdateApprovalProfileAPI,
    GetModalityProfilesAPI, UpdateModalityProfileAPI, GetAgentLoopSettingsAPI,
    UpdateAgentLoopSettingsAPI, GetMetadataProfileAPI, UpdateMetadataProfileAPI,
    GetToolchainSummaryProfileAPI, UpdateToolchainSummaryProfileAPI,
    AgentspaceListAPI, AgentspaceReadAPI, AgentspaceWriteAPI, AgentspaceMkdirAPI,
    AgentspaceRenameAPI, AgentspaceDeleteAPI, AgentspaceTrashListAPI,
    AgentspaceTrashRestoreAPI, AgentspaceTrashPurgeAPI, AgentspaceTrashEmptyAPI,
    AgentspaceLocksAPI, AgentspaceEventsAPI, ListSkillsAPI, ListLlmClientsAPI,
    ListLlmProfilesAPI, CreateLlmProfileAPI, UpdateLlmProfileAPI, DeleteLlmProfileAPI,
    SpaFallbackAPI, ChatWebSocketAPI,
)


def register_apis(gateway: IGatewaySystem, router: APIRouter) -> None:
    if any(isinstance(component, APIComponent) for component in gateway.system_components):
        raise RuntimeError("Gateway API components have already been registered")
    for component_type in _API_COMPONENT_TYPES:
        component = component_type()
        gateway.add_component(component)
        component.display(router)
