"""History content page."""

from typing import Any
from fastapi import APIRouter, Query
from entity.constant import SESSION_HISTORY_PAGE_DEFAULT_LIMIT, SESSION_HISTORY_PAGE_MAX_LIMIT
from gateway.api_support.sessions import require_session_loop
from interface.api_component import APIComponent
from interface.session_manager import ISessionManager


class HistoryPageAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/history/page", self.handler, methods=["GET"], name="get_session_history_page")

    async def handler(self, session_id: str, start_index: int = Query(0, ge=0), limit: int = Query(SESSION_HISTORY_PAGE_DEFAULT_LIMIT, ge=1, le=SESSION_HISTORY_PAGE_MAX_LIMIT)) -> Any:
        """Return full frontend content rows for a History index range."""
        loop = require_session_loop(self.get_system(ISessionManager), session_id)
        return loop.loop.get_session_history_page(start_index, limit)
