"""Complete Agentspace lock snapshot."""

from typing import Any
from fastapi import APIRouter
from interface.api_component import APIComponent
from interface.agentspace_service import IAgentspaceService


class AgentspaceLocksAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/agentspace/locks", self.handler, methods=["GET"], name="agentspace_locks")

    async def handler(self) -> dict[str, Any]:
        return {"locks": self.get_system(IAgentspaceService).locks_snapshot()}


api = AgentspaceLocksAPI()
