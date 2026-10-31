"""Read-only session variable pool."""

from fastapi import APIRouter, Response
from starlette.concurrency import run_in_threadpool
from entity.error import SessionVariableInputError, SessionVariableAccessError, SessionVariableLimitError, SessionVariableConflictError
from entity.puretype import SessionVariablePoolResponse
from gateway.api_support.domain_errors import raise_variable_http
from gateway.api_support.sessions import require_session
from interface.api_component import APIComponent
from interface.agentspace_service import IAgentspaceService
from interface.session_manager import ISessionManager


class SessionVariablesAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/variables", self.handler, methods=["GET"], name="get_session_variables")

    async def handler(self, session_id: str, response: Response) -> SessionVariablePoolResponse:
        """Read the shared variable pool without creating a Loop."""
        manager = self.get_system(ISessionManager)
        require_session(manager, session_id)
        response.headers["Cache-Control"] = "no-store"
        service = self.get_system(IAgentspaceService).session_variables
        try:
            result = await run_in_threadpool(service.read_pool, session_id)
        except (SessionVariableInputError, SessionVariableAccessError, SessionVariableLimitError, SessionVariableConflictError) as exc:
            raise_variable_http(exc)
        require_session(manager, session_id)
        return result
