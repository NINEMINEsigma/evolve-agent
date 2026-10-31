"""Global session tags."""

from typing import Any
from fastapi import APIRouter
from interface.api_component import APIComponent
from interface.session_manager import ISessionManager


class ListTagsAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/tags", self.handler, methods=["GET"], name="list_tags")

    async def handler(self) -> dict[str, Any]:
        """Return all existing session tags."""
        return {"tags": self.get_system(ISessionManager).get_all_tags()}
