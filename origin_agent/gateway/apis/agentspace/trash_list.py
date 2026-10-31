"""Agentspace trash entries and diagnostics."""

import asyncio
from typing import Any
from fastapi import APIRouter
from entity.error import AgentspaceError
from gateway.api_support.domain_errors import raise_agentspace_http
from interface.api_component import APIComponent
from interface.agentspace_service import IAgentspaceService


class AgentspaceTrashListAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/agentspace/trash", self.handler, methods=["GET"], name="agentspace_trash_list")

    async def handler(self) -> dict[str, Any]:
        try:
            entries = await asyncio.to_thread(self.get_system(IAgentspaceService).list_trash)
            return {"entries": entries}
        except AgentspaceError as exc:
            raise_agentspace_http(exc)


api = AgentspaceTrashListAPI()
