"""Current character avatar mapping."""

import asyncio
from fastapi import APIRouter, Response
from entity.puretype import CharacterAvatarsResponse
from interface.api_component import APIComponent
from interface.runtime_system import IRuntimeSystem
from interface.sandbox import ISandbox
from system.character_avatars import collect_character_avatars


class CharacterAvatarsAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/characters/avatars", self.handler, methods=["GET"], name="get_character_avatars", response_model=CharacterAvatarsResponse)

    async def handler(self, response: Response) -> CharacterAvatarsResponse:
        """Collect main and child Agent avatars without creating a Loop."""
        response.headers["Cache-Control"] = "no-store"
        return await asyncio.to_thread(collect_character_avatars, self.get_system(ISandbox), self.get_system(IRuntimeSystem))
