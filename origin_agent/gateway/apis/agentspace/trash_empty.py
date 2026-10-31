"""Empty Agentspace trash while retaining per-entry failures."""

import asyncio
import uuid
from typing import Any
from fastapi import APIRouter
from entity.error import AgentspaceError
from entity.puretype import AgentspaceOperationRequest
from gateway.api_support.domain_errors import raise_agentspace_http
from interface.api_component import APIComponent
from interface.agentspace_service import IAgentspaceService


class AgentspaceTrashEmptyAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/agentspace/trash", self.handler, methods=["DELETE"], name="agentspace_trash_empty")

    async def handler(self, payload: AgentspaceOperationRequest) -> dict[str, Any]:
        operation_id = payload.operation_id.strip() or uuid.uuid4().hex
        try:
            deleted, failures = await asyncio.to_thread(self.get_system(IAgentspaceService).empty_trash, operation_id)
            return {"deleted": deleted, "failures": failures, "operation_id": operation_id}
        except AgentspaceError as exc:
            raise_agentspace_http(exc)
