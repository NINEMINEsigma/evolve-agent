"""Flattened Profile DTO list."""

from typing import Any
from fastapi import APIRouter
from interface.api_component import APIComponent
from interface.llm_profile_store import ILLMProfileStore


class ListLlmProfilesAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/llm/profiles", self.handler, methods=["GET"], name="get_llm_profiles")

    async def handler(self) -> dict[str, Any]:
        """Return flat Profiles from the shared v2 root without its reference graph."""
        store = self.get_system(ILLMProfileStore)
        return {"profiles": [store.to_payload(profile) for profile in store.list_profiles()]}


api = ListLlmProfilesAPI()
