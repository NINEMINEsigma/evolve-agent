"""Permanently purge one Agentspace trash entry."""

import asyncio
import uuid
from typing import Any
from fastapi import APIRouter
from entity.error import AgentspaceError
from entity.puretype import AgentspaceOperationRequest
from gateway.api_support.domain_errors import raise_agentspace_http
from interface.api_component import APIComponent
from interface.agentspace_service import IAgentspaceService


class AgentspaceTrashPurgeAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/agentspace/trash/{entry_id}", self.handler, methods=["DELETE"], name="agentspace_trash_purge")

    async def handler(self, entry_id: str, payload: AgentspaceOperationRequest) -> dict[str, Any]:
        operation_id = payload.operation_id.strip() or uuid.uuid4().hex
        try:
            await asyncio.to_thread(self.get_system(IAgentspaceService).purge_trash, entry_id, operation_id)
            return {"success": True, "operation_id": operation_id}
        except AgentspaceError as exc:
            raise_agentspace_http(exc)


api = AgentspaceTrashPurgeAPI()
