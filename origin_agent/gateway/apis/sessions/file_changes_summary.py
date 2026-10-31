"""Session file change summary."""

from fastapi import APIRouter, Response
from starlette.concurrency import run_in_threadpool
from entity.puretype import SessionFileChangesSummary
from gateway.api_support.sessions import require_session
from interface.api_component import APIComponent
from interface.agentspace_service import IAgentspaceService
from interface.session_manager import ISessionManager


class SessionFileChangesSummaryAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/file-changes/summary", self.handler, methods=["GET"], name="get_session_file_changes_summary", response_model=SessionFileChangesSummary)

    async def handler(self, session_id: str, response: Response) -> SessionFileChangesSummary:
        manager = self.get_system(ISessionManager)
        require_session(manager, session_id)
        store = self.get_system(IAgentspaceService).file_changes
        try:
            result = await run_in_threadpool(store.get_summary, session_id)
        except FileNotFoundError:
            require_session(manager, session_id)
            raise
        require_session(manager, session_id)
        response.headers["Cache-Control"] = "no-store"
        return result


api = SessionFileChangesSummaryAPI()
