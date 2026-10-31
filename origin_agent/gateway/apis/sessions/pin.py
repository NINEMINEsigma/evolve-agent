"""Session pin toggle."""

import logging
from typing import Any
from fastapi import APIRouter
from gateway.api_support.sessions import require_session
from interface.api_component import APIComponent
from interface.session_manager import ISessionManager

logger = logging.getLogger(__name__)


class PinSessionAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/pin", self.handler, methods=["POST"], name="pin_session_endpoint")

    async def handler(self, session_id: str) -> dict[str, Any]:
        """Toggle the session pinned state."""
        manager = self.get_system(ISessionManager)
        require_session(manager, session_id)
        pinned = manager.toggle_pin(session_id)
        logger.info("Toggle pin | session=%s pinned=%s", session_id, pinned)
        return {"pinned": pinned, "session_id": session_id}
