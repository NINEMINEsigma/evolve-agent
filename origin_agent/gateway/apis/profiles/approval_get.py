"""Authoritative approval Profile state."""

from typing import Any
from fastapi import APIRouter
from interface.api_component import APIComponent
from interface.approval_system import IApprovalSystem


class GetApprovalProfileAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/approval/profile", self.handler, methods=["GET"], name="get_approval_profile")

    async def handler(self) -> Any:
        """Return the authoritative project-level approval Profile state."""
        return self.get_system(IApprovalSystem).backend_manager.get_state()


api = GetApprovalProfileAPI()
