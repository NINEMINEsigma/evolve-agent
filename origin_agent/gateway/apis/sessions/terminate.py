"""Manual session termination without rotation."""

import logging
from typing import Any
from fastapi import APIRouter
from entity.constant import GatewayErrorCode
from entity.puretype import Loop
from gateway.api_support.sessions import require_session, require_session_loop
from gateway.http_boundary import business_http_error, require_business_http
from interface.api_component import APIComponent
from interface.session_manager import ISessionManager
from interface.subagent_orchestrator import ISubAgentOrchestrator

logger = logging.getLogger(__name__)


class TerminateSessionAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/terminate", self.handler, methods=["POST"], name="terminate_session_endpoint")

    async def handler(self, session_id: str) -> Any:
        """Archive and summarize a session without rotation; colloquy is excluded."""
        manager = self.get_system(ISessionManager)
        info = require_session(manager, session_id)
        if info.loop_type == Loop.colloquy:
            logger.warning("Terminate session rejected (colloquy) | session=%s", session_id)
            raise business_http_error(403, GatewayErrorCode.COLLOQUY_OPERATION_FORBIDDEN, "Colloquy session cannot be terminated", details={"session_id": session_id})
        require_session_loop(manager, session_id)
        logger.info("Terminate session | session=%s", session_id)
        await self.get_system(ISubAgentOrchestrator).shutdown(session_id)
        require_business_http(self.gateway.admission)
        loop = require_session_loop(manager, session_id)
        result = await loop.loop.terminate_session()
        logger.info("Terminate session complete | session=%s terminated=%s warnings=%d", session_id, result.terminated, len(result.metadata_warnings))
        return result


api = TerminateSessionAPI()
