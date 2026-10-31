"""Create one LLM Profile through the shared Store transaction."""

from fastapi import APIRouter
from entity.constant import GatewayErrorCode
from entity.error import ProfileNotFoundError, ProfileConflictError
from entity.puretype import LLMProfilePayload, LLMProfileMutationResponse
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent
from interface.llm_profile_store import ILLMProfileStore


class CreateLlmProfileAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/llm/profiles", self.handler, methods=["POST"], name="create_llm_profile", response_model=LLMProfileMutationResponse)

    async def handler(self, payload: LLMProfilePayload) -> LLMProfileMutationResponse:
        """Create a single LLM Profile."""
        store = self.get_system(ILLMProfileStore)
        try:
            with store.locked():
                profile = store.create_profile(payload)
                response_payload = store.to_payload(profile)
            return LLMProfileMutationResponse(profile=response_payload)
        except ProfileNotFoundError as exc:
            raise business_http_error(404, GatewayErrorCode.PROFILE_NOT_FOUND, str(exc)) from exc
        except ProfileConflictError as exc:
            raise business_http_error(409, GatewayErrorCode.PROFILE_CONFLICT, str(exc)) from exc


api = CreateLlmProfileAPI()
