"""Main-session disgust action."""

import logging
from typing import Any
from fastapi import APIRouter
from gateway.api_support.sessions import require_session_loop
from interface.api_component import APIComponent
from interface.session_manager import ISessionManager

logger = logging.getLogger(__name__)


class DisgustSessionAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/disgust/{session_id}", self.handler, methods=["POST"], name="http_disgust")

    async def handler(self, session_id: str) -> dict[str, Any]:
        """Apply disgust even while WebSocket processing is busy."""
        logger.info("HTTP disgust | session=%s", session_id)
        loop = require_session_loop(self.get_system(ISessionManager), session_id)
        loop.loop.disgust()
        return {"disgusted": True, "session_id": session_id}
