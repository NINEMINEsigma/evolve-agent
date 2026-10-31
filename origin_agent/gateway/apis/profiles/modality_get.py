"""Global per-modality fallback references."""

from fastapi import APIRouter
from entity.puretype import ModalityProfileStates
from gateway.api_support.profiles import get_modality_profile_states
from interface.api_component import APIComponent
from interface.llm_profile_store import ILLMProfileStore


class GetModalityProfilesAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/modality/profiles", self.handler, methods=["GET"], name="get_modality_profiles")

    async def handler(self) -> ModalityProfileStates:
        """Return separate image, audio and video fallback Profile states."""
        return get_modality_profile_states(self.get_system(ILLMProfileStore))


api = GetModalityProfilesAPI()
