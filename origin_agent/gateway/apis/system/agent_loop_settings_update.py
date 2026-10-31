"""Persist a candidate global tool-loop setting before publishing it."""

from fastapi import APIRouter, Response
from entity.puretype import AgentLoopSettingsState, AgentLoopSettingsUpdateRequest
from gateway.http_boundary import require_business_http
from interface.api_component import APIComponent
from interface.runtime_system import IRuntimeSystem


class UpdateAgentLoopSettingsAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/agent-loop/settings", self.handler, methods=["PUT"], name="put_agent_loop_settings", response_model=AgentLoopSettingsState)

    async def handler(self, payload: AgentLoopSettingsUpdateRequest, response: Response) -> AgentLoopSettingsState:
        """Commit a candidate synchronously before exposing the new effective value."""
        require_business_http(self.gateway.admission)
        state = self.get_system(IRuntimeSystem).set_max_tool_turns(payload.max_tool_turns)
        response.headers["Cache-Control"] = "no-store"
        return state


api = UpdateAgentLoopSettingsAPI()
