"""Current character profile catalogue."""

import asyncio
from fastapi import APIRouter, Response
from entity.puretype import CharacterProfilesResponse
from interface.api_component import APIComponent
from interface.llm_profile_store import ILLMProfileStore
from interface.sandbox import ISandbox
from system.character_profiles import collect_character_profiles


class CharacterProfilesAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/characters/profiles", self.handler, methods=["GET"], name="get_character_profiles", response_model=CharacterProfilesResponse)

    async def handler(self, response: Response) -> CharacterProfilesResponse:
        """Collect character prompts and per-entry errors without exposing credentials."""
        response.headers["Cache-Control"] = "no-store"
        return await asyncio.to_thread(collect_character_profiles, self.get_system(ISandbox), self.get_system(ILLMProfileStore))
