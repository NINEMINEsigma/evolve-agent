"""Restore one Agentspace trash entry."""

import asyncio
import uuid
from typing import Any
from fastapi import APIRouter
from entity.error import AgentspaceError
from entity.puretype import AgentspaceOperationRequest
from gateway.api_support.domain_errors import raise_agentspace_http
from interface.api_component import APIComponent
from interface.agentspace_service import IAgentspaceService


class AgentspaceTrashRestoreAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/agentspace/trash/{entry_id}/restore", self.handler, methods=["POST"], name="agentspace_trash_restore")

    async def handler(self, entry_id: str, payload: AgentspaceOperationRequest) -> dict[str, Any]:
        operation_id = payload.operation_id.strip() or uuid.uuid4().hex
        try:
            entry, restored_path = await asyncio.to_thread(self.get_system(IAgentspaceService).restore_trash, entry_id, operation_id)
            return {"entry": entry, "restored_path": restored_path, "operation_id": operation_id}
        except AgentspaceError as exc:
            raise_agentspace_http(exc)


api = AgentspaceTrashRestoreAPI()
