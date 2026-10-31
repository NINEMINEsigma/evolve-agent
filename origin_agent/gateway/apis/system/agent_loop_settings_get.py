"""Read effective global tool-loop settings."""

from fastapi import APIRouter, Response
from entity.puretype import AgentLoopSettingsState
from interface.api_component import APIComponent
from interface.runtime_system import IRuntimeSystem


class GetAgentLoopSettingsAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/agent-loop/settings", self.handler, methods=["GET"], name="get_agent_loop_settings", response_model=AgentLoopSettingsState)

    async def handler(self, response: Response) -> AgentLoopSettingsState:
        """Read settings without creating a Loop or writing default settings."""
        response.headers["Cache-Control"] = "no-store"
        return self.get_system(IRuntimeSystem).get_agent_loop_settings()
