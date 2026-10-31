"""Session Cron task metadata."""

from typing import Any
from fastapi import APIRouter
from gateway.api_support.sessions import require_session
from interface.api_component import APIComponent
from interface.cron_router import ICronRouter
from interface.session_manager import ISessionManager


class ListSessionCronTasksAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/cron-tasks", self.handler, methods=["GET"], name="list_cron_tasks_endpoint")

    async def handler(self, session_id: str) -> dict[str, Any]:
        """List scheduled tasks belonging to the selected session."""
        require_session(self.get_system(ISessionManager), session_id)
        return {"tasks": self.get_system(ICronRouter).list_cron_tasks_for_session(session_id)}


api = ListSessionCronTasksAPI()
