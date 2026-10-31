"""Session Shell metadata."""

from typing import Any
from fastapi import APIRouter
from gateway.api_support.sessions import require_session
from interface.api_component import APIComponent
from interface.session_manager import ISessionManager
from interface.shell_manager import IShellManager


class ListSessionShellsAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/shells", self.handler, methods=["GET"], name="list_shells_endpoint")

    async def handler(self, session_id: str) -> dict[str, Any]:
        """List all Shell metadata belonging to the selected main session."""
        require_session(self.get_system(ISessionManager), session_id)
        return {"shells": self.get_system(IShellManager).list_shells(session_id)}
