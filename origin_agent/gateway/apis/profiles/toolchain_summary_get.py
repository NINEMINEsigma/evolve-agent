"""Global toolchain-summary Profile state."""

from typing import Any
from fastapi import APIRouter
from interface.api_component import APIComponent
from interface.session_metadata_service import ISessionMetadataService


class GetToolchainSummaryProfileAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/toolchain-summary/profile", self.handler, methods=["GET"], name="get_toolchain_summary_profile")

    async def handler(self) -> Any:
        """Return the authoritative global toolchain-summary Profile state."""
        return self.get_system(ISessionMetadataService).get_toolchain_summary_state()


api = GetToolchainSummaryProfileAPI()
