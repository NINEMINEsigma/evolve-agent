"""Authoritative session runtime status."""

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool
from entity.puretype import SessionRuntimeStatus
from interface.api_component import APIComponent
from interface.agentspace_service import IAgentspaceService
from interface.frontend_sink import IFrontendSink
from interface.session_manager import ISessionManager


class SessionStatusAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/status", self.handler, methods=["GET"], name="get_session_status")

    async def handler(self, session_id: str, conn_token: str | None = None) -> SessionRuntimeStatus:
        """Return existence, occupation and the current main-session activity."""
        manager = self.get_system(ISessionManager)
        exists = manager.exists(session_id) and not manager.is_session_deleting(session_id)
        sink = self.get_system(IFrontendSink)
        occupied = bool(exists and sink.is_session_occupied(session_id, conn_token))
        managed_loop = manager.get_loop(session_id) if exists else None
        activity = managed_loop.loop.get_main_session_activity() if managed_loop is not None else None
        processing = bool(managed_loop is not None and managed_loop.loop.is_active())
        visual_resources = await run_in_threadpool(
            self.get_system(IAgentspaceService).visual_resources.get_all_states, session_id,
        ) if exists else None
        return SessionRuntimeStatus(
            session_id=session_id, exists=exists, occupied=occupied,
            processing=processing, activity=activity, visual_resources=visual_resources,
        )
