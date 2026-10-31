"""Session file change page."""

from fastapi import APIRouter, Query, Response
from starlette.concurrency import run_in_threadpool
from entity.constant import SESSION_FILE_CHANGES_DEFAULT_LIMIT, SESSION_FILE_CHANGES_MAX_LIMIT
from entity.puretype import SessionFileChangesPage
from gateway.api_support.sessions import require_session
from interface.api_component import APIComponent
from interface.agentspace_service import IAgentspaceService
from interface.session_manager import ISessionManager


class SessionFileChangesAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/file-changes", self.handler, methods=["GET"], name="get_session_file_changes", response_model=SessionFileChangesPage)

    async def handler(
        self, session_id: str, response: Response,
        offset: int = Query(0, ge=0),
        limit: int = Query(SESSION_FILE_CHANGES_DEFAULT_LIMIT, ge=1, le=SESSION_FILE_CHANGES_MAX_LIMIT),
    ) -> SessionFileChangesPage:
        manager = self.get_system(ISessionManager)
        require_session(manager, session_id)
        store = self.get_system(IAgentspaceService).file_changes
        try:
            result = await run_in_threadpool(store.get_page, session_id, offset=offset, limit=limit)
        except FileNotFoundError:
            require_session(manager, session_id)
            raise
        require_session(manager, session_id)
        response.headers["Cache-Control"] = "no-store"
        return result


api = SessionFileChangesAPI()
