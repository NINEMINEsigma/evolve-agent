"""Update a Profile and propagate reference changes."""

from fastapi import APIRouter
from entity.constant import GatewayErrorCode, SESSIONS_DIR_NAME
from entity.error import ProfileNotFoundError, ProfileConflictError
from entity.puretype import LLMProfileUpdateRequest, LLMProfileMutationResponse
from gateway.api_support.profiles import get_modality_profile_states
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent
from interface.approval_system import IApprovalSystem
from interface.frontend_sink import IFrontendSink
from interface.llm_profile_store import ILLMProfileStore
from interface.runtime_system import IRuntimeSystem
from interface.session_metadata_service import ISessionMetadataService
from system.session_store import SessionStore


class UpdateLlmProfileAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/llm/profiles", self.handler, methods=["PUT"], name="update_llm_profile", response_model=LLMProfileMutationResponse)

    async def handler(self, payload: LLMProfileUpdateRequest) -> LLMProfileMutationResponse:
        """Update one LLM Profile in place and broadcast any rename."""
        store = self.get_system(ILLMProfileStore)
        metadata_service = self.get_system(ISessionMetadataService)
        old_name = payload.profile_name
        try:
            with store.locked():
                profile = store.update_profile(old_name, payload.profile)
                # 根对象已提交，后续指针写盘失败也不能保留旧客户端缓存。
                manager = self.get_system(IApprovalSystem).backend_manager
                manager.invalidate()
                new_name = profile.name
                if new_name != old_name:
                    SessionStore(self.get_system(IRuntimeSystem).context.workspace / SESSIONS_DIR_NAME).replace_profile_name_pointers(old_name, new_name)
                response_payload = store.to_payload(profile)
                metadata_state = metadata_service.get_state()
                toolchain_summary_state = metadata_service.get_toolchain_summary_state()
                modality_states = get_modality_profile_states(store)
            sink = self.get_system(IFrontendSink)
            failures: list[str] = []
            if new_name != old_name:
                failures = await sink.broadcast_profile_change("renamed", old_name, new_name)
            approval_state = manager.get_state()
            approval_failures = await sink.broadcast_approval_profile_change(approval_state)
            metadata_failures = await sink.broadcast_metadata_profile_change(metadata_state)
            toolchain_summary_failures = await sink.broadcast_toolchain_summary_profile_change(toolchain_summary_state)
            modality_failures = await sink.broadcast_modality_profile_change(modality_states)
            return LLMProfileMutationResponse(profile=response_payload, notification_failures=failures + approval_failures + metadata_failures + toolchain_summary_failures + modality_failures)
        except ProfileNotFoundError as exc:
            raise business_http_error(404, GatewayErrorCode.PROFILE_NOT_FOUND, str(exc)) from exc
        except ProfileConflictError as exc:
            raise business_http_error(409, GatewayErrorCode.PROFILE_CONFLICT, str(exc)) from exc
