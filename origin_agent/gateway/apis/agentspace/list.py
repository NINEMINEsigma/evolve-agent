"""Agentspace directory listing."""

import asyncio
from typing import Any
from fastapi import APIRouter
from entity.error import AgentspaceError
from gateway.api_support.domain_errors import raise_agentspace_http
from interface.api_component import APIComponent
from interface.agentspace_service import IAgentspaceService


class AgentspaceListAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/agentspace/list", self.handler, methods=["GET"], name="agentspace_list")

    async def handler(self, path: str = "") -> dict[str, Any]:
        try:
            entries = await asyncio.to_thread(self.get_system(IAgentspaceService).list_directory, path)
            return {"entries": [{**entry.model_dump(mode="json"), "type": entry.kind.value} for entry in entries]}
        except AgentspaceError as exc:
            raise_agentspace_http(exc)


api = AgentspaceListAPI()
