"""Main-session media instances and complete-History aggregates."""

from fastapi import APIRouter, Query, Response
from entity.constant import SESSION_MEDIA_DEFAULT_OFFSET, SESSION_MEDIA_DEFAULT_LIMIT, SESSION_MEDIA_MAX_LIMIT
from entity.puretype import SessionMediaListResponse, SessionStatus
from gateway.api_support.media import require_media_loop
from gateway.api_support.sessions import require_session
from interface.api_component import APIComponent
from interface.session_manager import ISessionManager


class HistoryMediaListAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/history/media", self.handler, methods=["GET"], name="get_session_media")

    async def handler(self, session_id: str, response: Response, offset: int = Query(SESSION_MEDIA_DEFAULT_OFFSET, ge=0), limit: int = Query(SESSION_MEDIA_DEFAULT_LIMIT, ge=1, le=SESSION_MEDIA_MAX_LIMIT)) -> SessionMediaListResponse:
        manager = self.get_system(ISessionManager)
        loop = require_media_loop(manager, session_id, writable=False)
        response.headers["Cache-Control"] = "no-store"
        info = require_session(manager, session_id)
        return loop.loop.get_session_media(offset=offset, limit=limit, editable=info.status != SessionStatus.archived)
