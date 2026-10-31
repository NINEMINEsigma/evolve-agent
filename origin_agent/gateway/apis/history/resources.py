"""Complete History resource index."""

from typing import Any
from fastapi import APIRouter
from gateway.api_support.sessions import require_session_loop
from interface.api_component import APIComponent
from interface.session_manager import ISessionManager


class HistoryResourcesAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/history/resources", self.handler, methods=["GET"], name="get_session_history_resources")

    async def handler(self, session_id: str) -> Any:
        """Return image and download resources from the complete in-memory History."""
        loop = require_session_loop(self.get_system(ISessionManager), session_id)
        return loop.loop.get_session_history_resources()
