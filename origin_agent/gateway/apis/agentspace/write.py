"""Version-checked Agentspace file write."""

import asyncio
import uuid
from typing import Any
from fastapi import APIRouter
from entity.error import AgentspaceError
from entity.puretype import AgentspaceWriteRequest
from gateway.api_support.domain_errors import raise_agentspace_http
from interface.api_component import APIComponent
from interface.agentspace_service import IAgentspaceService


class AgentspaceWriteAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/agentspace/write", self.handler, methods=["POST"], name="agentspace_write")

    async def handler(self, payload: AgentspaceWriteRequest) -> dict[str, Any]:
        operation_id = payload.operation_id or uuid.uuid4().hex
        try:
            snapshot = await asyncio.to_thread(self.get_system(IAgentspaceService).write_file, payload.path, payload.content, payload.expected_version, operation_id)
            return {**snapshot.model_dump(mode="json"), "operation_id": operation_id}
        except AgentspaceError as exc:
            raise_agentspace_http(exc)


api = AgentspaceWriteAPI()
