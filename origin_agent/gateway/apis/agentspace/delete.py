"""User deletion into the Agentspace trash."""

import asyncio
import uuid
from typing import Any
from fastapi import APIRouter
from entity.error import AgentspaceError
from entity.puretype import AgentspacePathRequest
from gateway.api_support.domain_errors import raise_agentspace_http
from interface.api_component import APIComponent
from interface.agentspace_service import IAgentspaceService


class AgentspaceDeleteAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/agentspace/delete", self.handler, methods=["POST"], name="agentspace_delete")

    async def handler(self, payload: AgentspacePathRequest) -> dict[str, Any]:
        """Move user-deleted entries into the Agentspace trash."""
        operation_id = payload.operation_id or uuid.uuid4().hex
        try:
            entry = await asyncio.to_thread(self.get_system(IAgentspaceService).move_to_trash, payload.path, operation_id)
            return {"entry": entry, "operation_id": operation_id}
        except AgentspaceError as exc:
            raise_agentspace_http(exc)


api = AgentspaceDeleteAPI()
