"""Set or clear the approval Profile reference."""

import logging
from fastapi import APIRouter
from entity.constant import GatewayErrorCode
from entity.error import ProfileNotFoundError
from entity.puretype import ApprovalProfileUpdateRequest, ApprovalProfileMutationResponse
from gateway.api_support.profiles import missing_profile_connection_fields
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent
from interface.approval_system import IApprovalSystem
from interface.frontend_sink import IFrontendSink
from interface.llm_profile_store import ILLMProfileStore

logger = logging.getLogger(__name__)


class UpdateApprovalProfileAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/approval/profile", self.handler, methods=["PUT"], name="put_approval_profile")

    async def handler(self, payload: ApprovalProfileUpdateRequest) -> ApprovalProfileMutationResponse:
        """Set or clear the project approval Profile; null clears the reference."""
        store = self.get_system(ILLMProfileStore)
        manager = self.get_system(IApprovalSystem).backend_manager
        with store.locked():
            if payload.profile_name is None:
                previous = store.get_approval_profile()
                store.set_approval_profile(None)
                logger.info("Approval profile cleared | previous=%s", previous.name if previous else None)
            else:
                try:
                    profile = store.get_profile(payload.profile_name)
                except ProfileNotFoundError as exc:
                    raise business_http_error(404, GatewayErrorCode.PROFILE_NOT_FOUND, f"Profile not found: {payload.profile_name!r}") from exc
                missing = missing_profile_connection_fields(profile)
                if missing:
                    raise business_http_error(409, GatewayErrorCode.PROFILE_CONFLICT, f"Approval Profile {profile.name!r} is missing required fields: " + ", ".join(missing), details={"profile_name": profile.name, "missing_fields": missing})
                previous = store.get_approval_profile()
                store.set_approval_profile(profile)
                logger.info("Approval profile set | name=%s model=%s client=%s", profile.name, profile.model, profile.llm_client_name)
            manager.invalidate()
        state = manager.get_state()
        failures = await self.get_system(IFrontendSink).broadcast_approval_profile_change(state)
        return ApprovalProfileMutationResponse(state=state, notification_failures=failures)
