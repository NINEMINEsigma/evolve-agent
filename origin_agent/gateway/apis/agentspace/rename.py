"""Rename an Agentspace entry without replacement."""

import asyncio
import uuid
from typing import Any
from fastapi import APIRouter
from entity.error import AgentspaceError
from entity.puretype import AgentspaceRenameRequest
from gateway.api_support.domain_errors import raise_agentspace_http
from interface.api_component import APIComponent
from interface.agentspace_service import IAgentspaceService


class AgentspaceRenameAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/agentspace/rename", self.handler, methods=["POST"], name="agentspace_rename")

    async def handler(self, payload: AgentspaceRenameRequest) -> dict[str, Any]:
        operation_id = payload.operation_id or uuid.uuid4().hex
        try:
            old_path, new_path = await asyncio.to_thread(self.get_system(IAgentspaceService).rename_path, payload.path, payload.new_name, operation_id)
            return {"old_path": old_path, "new_path": new_path, "operation_id": operation_id}
        except AgentspaceError as exc:
            raise_agentspace_http(exc)


api = AgentspaceRenameAPI()
