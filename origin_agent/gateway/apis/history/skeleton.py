"""Full History skeleton or append-only suffix."""

from typing import Any
from fastapi import APIRouter, Query
from entity.constant import GatewayErrorCode
from gateway.api_support.sessions import require_session_loop
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent
from interface.session_manager import ISessionManager


class HistorySkeletonAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/history/skeleton", self.handler, methods=["GET"], name="get_session_history_skeleton")

    async def handler(self, session_id: str, start_index: int = Query(0, ge=0)) -> Any:
        """Return the complete frontend skeleton or a suffix by History index."""
        loop = require_session_loop(self.get_system(ISessionManager), session_id)
        if start_index > loop.loop.history.count:
            raise business_http_error(400, GatewayErrorCode.HISTORY_INDEX_OUT_OF_RANGE, "History start index is out of range", details={"session_id": session_id})
        return loop.loop.get_session_history_skeleton(start_index)


api = HistorySkeletonAPI()
