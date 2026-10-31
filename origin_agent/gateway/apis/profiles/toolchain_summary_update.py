"""Select the global toolchain-summary Profile reference."""

from fastapi import APIRouter
from entity.constant import GatewayErrorCode
from entity.error import ProfileNotFoundError, MetadataProfileUnavailableError
from entity.puretype import ToolchainSummaryProfileUpdateRequest, ToolchainSummaryProfileMutationResponse
from gateway.api_support.domain_errors import raise_metadata_http
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent
from interface.frontend_sink import IFrontendSink
from interface.llm_profile_store import ILLMProfileStore
from interface.session_metadata_service import ISessionMetadataService


class UpdateToolchainSummaryProfileAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/toolchain-summary/profile", self.handler, methods=["PUT"], name="put_toolchain_summary_profile", response_model=ToolchainSummaryProfileMutationResponse)

    async def handler(self, payload: ToolchainSummaryProfileUpdateRequest) -> ToolchainSummaryProfileMutationResponse:
        """Set or clear the global toolchain-summary Profile reference."""
        store = self.get_system(ILLMProfileStore)
        service = self.get_system(ISessionMetadataService)
        try:
            with store.locked():
                profile = store.get_profile(payload.profile_name) if payload.profile_name is not None else None
                state = service.select_toolchain_summary_profile(profile)
        except ProfileNotFoundError as exc:
            raise business_http_error(404, GatewayErrorCode.PROFILE_NOT_FOUND, f"Profile not found: {payload.profile_name!r}") from exc
        except MetadataProfileUnavailableError as exc:
            raise_metadata_http(exc)
        failures = await self.get_system(IFrontendSink).broadcast_toolchain_summary_profile_change(state)
        return ToolchainSummaryProfileMutationResponse(state=state, notification_failures=failures)
