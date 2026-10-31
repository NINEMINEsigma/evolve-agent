"""Active child-session snapshot."""

from fastapi import APIRouter
from entity.puretype import SubAgentSnapshotResponse
from gateway.api_support.sessions import require_session
from interface.api_component import APIComponent
from interface.session_manager import ISessionManager
from interface.subagent_orchestrator import ISubAgentOrchestrator


class SessionSubagentsAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/subagents", self.handler, methods=["GET"], name="get_session_subagents")

    async def handler(self, session_id: str) -> SubAgentSnapshotResponse:
        """Return active child sessions, including an empty snapshot."""
        require_session(self.get_system(ISessionManager), session_id)
        snapshot = self.get_system(ISubAgentOrchestrator).get_snapshot(parent_session_id=session_id)
        return SubAgentSnapshotResponse(session_id=session_id, subagents=snapshot.subagents)
