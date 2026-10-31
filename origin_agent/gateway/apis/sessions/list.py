"""Session list endpoint."""

from typing import Any
from fastapi import APIRouter
from interface.api_component import APIComponent
from interface.session_manager import ISessionManager


class ListSessionsAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions", self.handler, methods=["GET"], name="list_sessions")

    async def handler(self) -> dict[str, Any]:
        """Return sessions and their metadata."""
        return {"sessions": self.get_system(ISessionManager).get_all()}


api = ListSessionsAPI()
