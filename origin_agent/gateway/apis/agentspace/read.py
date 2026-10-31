"""Versioned Agentspace file snapshot."""

import asyncio
from typing import Any
from fastapi import APIRouter
from entity.error import AgentspaceError
from gateway.api_support.domain_errors import raise_agentspace_http
from interface.api_component import APIComponent
from interface.agentspace_service import IAgentspaceService


class AgentspaceReadAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/agentspace/read", self.handler, methods=["GET"], name="agentspace_read")

    async def handler(self, path: str = "") -> Any:
        try:
            return await asyncio.to_thread(self.get_system(IAgentspaceService).read_file, path)
        except AgentspaceError as exc:
            raise_agentspace_http(exc)
