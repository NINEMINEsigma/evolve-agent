"""User-requested Shell stop, including cleanup pending."""

import logging
from typing import Any
from fastapi import APIRouter
from entity.constant import GatewayErrorCode
from entity.error import ShellAccessError
from gateway.api_support.sessions import require_session
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent
from interface.session_manager import ISessionManager
from interface.shell_manager import IShellManager

logger = logging.getLogger(__name__)


class StopSessionShellAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/shells/{shell_id}/stop", self.handler, methods=["POST"], name="stop_shell_endpoint")

    async def handler(self, session_id: str, shell_id: str) -> Any:
        """Stop a Shell belonging to the selected main session."""
        require_session(self.get_system(ISessionManager), session_id)
        logger.info("Stop Shell from frontend | session=%s shell=%s", session_id, shell_id)
        try:
            return await self.get_system(IShellManager).stop_shell_for_user(session_id, shell_id)
        except ShellAccessError as exc:
            raise business_http_error(404, GatewayErrorCode.SHELL_NOT_FOUND, str(exc), details={"session_id": session_id, "shell_id": shell_id}) from exc


api = StopSessionShellAPI()
