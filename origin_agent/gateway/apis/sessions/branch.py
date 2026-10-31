"""Single-source archived-session continuation."""

import logging
from typing import Any
from fastapi import APIRouter
from entity.constant import GatewayErrorCode
from gateway.api_support.sessions import validate_merge_sources, require_session_loop
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent
from interface.session_manager import ISessionManager

logger = logging.getLogger(__name__)


class BranchSessionAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/branch", self.handler, methods=["POST"], name="branch_session_endpoint")

    async def handler(self, session_id: str) -> Any:
        """Create a continuation from an archived source using single-source merge."""
        logger.info("Branch session | source=%s", session_id)
        manager = self.get_system(ISessionManager)
        validate_merge_sources(manager, [session_id])
        loop = require_session_loop(manager, session_id)
        result = await loop.loop.merge_sessions([session_id])
        if not result.merged:
            raise business_http_error(409, GatewayErrorCode.SESSION_MERGE_REJECTED, result.error or "Session merge rejected", details={"sources": [session_id]})
        return result


api = BranchSessionAPI()
