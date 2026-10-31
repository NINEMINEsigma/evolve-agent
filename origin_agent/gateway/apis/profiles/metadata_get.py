"""Global metadata Profile state."""

from typing import Any
from fastapi import APIRouter
from interface.api_component import APIComponent
from interface.session_metadata_service import ISessionMetadataService


class GetMetadataProfileAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/metadata/profile", self.handler, methods=["GET"], name="get_metadata_profile")

    async def handler(self) -> Any:
        """Return the authoritative global metadata Profile state."""
        return self.get_system(ISessionMetadataService).get_state()
