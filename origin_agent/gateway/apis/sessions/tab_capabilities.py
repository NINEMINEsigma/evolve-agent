"""Lightweight session tab capabilities."""

from fastapi import APIRouter, Response
from starlette.concurrency import run_in_threadpool
from entity.error import SessionVariableInputError, SessionVariableAccessError, SessionVariableLimitError, SessionVariableConflictError
from entity.puretype import SessionTabCapabilities
from gateway.api_support.domain_errors import raise_variable_http
from gateway.api_support.media import require_media_loop
from gateway.api_support.sessions import require_session
from interface.api_component import APIComponent
from interface.agentspace_service import IAgentspaceService
from interface.session_manager import ISessionManager


class SessionTabCapabilitiesAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/tab-capabilities", self.handler, methods=["GET"], name="get_session_tab_capabilities", response_model=SessionTabCapabilities)

    async def handler(self, session_id: str, response: Response) -> SessionTabCapabilities:
        """Return lightweight content capabilities for session-dependent tabs."""
        manager = self.get_system(ISessionManager)
        loop = require_media_loop(manager, session_id, writable=False)
        service = self.get_system(IAgentspaceService).session_variables
        try:
            variables_available = await run_in_threadpool(service.has_visible_content, session_id)
        except (SessionVariableInputError, SessionVariableAccessError, SessionVariableLimitError, SessionVariableConflictError) as exc:
            raise_variable_http(exc)
        require_session(manager, session_id)
        response.headers["Cache-Control"] = "no-store"
        return SessionTabCapabilities(session_id=session_id, media_count=loop.loop.get_session_media_count(), variables_available=variables_available)
