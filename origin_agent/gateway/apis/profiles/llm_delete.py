"""Delete a Profile and switch only affected idle main sessions."""

from fastapi import APIRouter
from entity.constant import GatewayErrorCode, SESSIONS_DIR_NAME
from entity.error import ProfileNotFoundError, ProfileConflictError
from entity.puretype import LLMProfileDeleteRequest, LLMProfileDeleteResult
from gateway.api_support.profiles import get_modality_profile_states
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent
from interface.approval_system import IApprovalSystem
from interface.frontend_sink import IFrontendSink
from interface.llm_profile_store import ILLMProfileStore
from interface.runtime_system import IRuntimeSystem
from interface.session_manager import ISessionManager
from interface.session_metadata_service import ISessionMetadataService
from system.session_store import SessionStore


class DeleteLlmProfileAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/llm/profiles", self.handler, methods=["DELETE"], name="delete_llm_profile", response_model=LLMProfileDeleteResult)

    async def handler(self, payload: LLMProfileDeleteRequest) -> LLMProfileDeleteResult:
        """Delete a Profile, switching only currently idle affected main sessions."""
        store = self.get_system(ILLMProfileStore)
        metadata_service = self.get_system(ISessionMetadataService)
        try:
            with store.locked():
                source = store.get_profile(payload.profile_name)
                replacement = store.get_profile(payload.replacement_profile_name) if payload.replacement_profile_name is not None else None
                if replacement is source:
                    raise ProfileConflictError("replacement Profile must differ from deleted Profile")
                store.assert_removable(source, clear_global_selections=True)
                store.remove_profile(payload.profile_name, clear_global_selections=True)
                self.get_system(IApprovalSystem).backend_manager.invalidate()
                switched, busy = self.get_system(ISessionManager).replace_idle_loops_using_profile(source, replacement)
                SessionStore(self.get_system(IRuntimeSystem).context.workspace / SESSIONS_DIR_NAME).replace_profile_name_pointers(payload.profile_name, payload.replacement_profile_name)
                metadata_state = metadata_service.get_state()
                toolchain_summary_state = metadata_service.get_toolchain_summary_state()
                modality_states = get_modality_profile_states(store)
            sink = self.get_system(IFrontendSink)
            failures = await sink.broadcast_profile_change("deleted", payload.profile_name, payload.replacement_profile_name)
            approval_state = self.get_system(IApprovalSystem).backend_manager.get_state()
            approval_failures = await sink.broadcast_approval_profile_change(approval_state)
            metadata_failures = await sink.broadcast_metadata_profile_change(metadata_state)
            toolchain_summary_failures = await sink.broadcast_toolchain_summary_profile_change(toolchain_summary_state)
            modality_failures = await sink.broadcast_modality_profile_change(modality_states)
            return LLMProfileDeleteResult(
                deleted=True, profile_name=payload.profile_name,
                replacement_profile_name=payload.replacement_profile_name,
                switched_sessions=switched, pending_sessions=busy,
                notification_failures=failures + approval_failures + metadata_failures + toolchain_summary_failures + modality_failures,
            )
        except ProfileNotFoundError as exc:
            raise business_http_error(404, GatewayErrorCode.PROFILE_NOT_FOUND, str(exc)) from exc
        except ProfileConflictError as exc:
            raise business_http_error(409, GatewayErrorCode.PROFILE_CONFLICT, str(exc)) from exc


api = DeleteLlmProfileAPI()
