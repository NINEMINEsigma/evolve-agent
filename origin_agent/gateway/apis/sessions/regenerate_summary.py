"""Manual session summary regeneration."""

import logging
from typing import Any
from fastapi import APIRouter
from entity.constant import GatewayErrorCode
from entity.error import MetadataProfileUnavailableError, MetadataGenerationError
from entity.puretype import Loop
from gateway.api_support.domain_errors import raise_metadata_http
from gateway.api_support.sessions import require_session
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent
from interface.session_manager import ISessionManager
from interface.session_metadata_service import ISessionMetadataService

logger = logging.getLogger(__name__)


class RegenerateSessionSummaryAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/regenerate-summary", self.handler, methods=["POST"], name="regenerate_summary_endpoint")

    async def handler(self, session_id: str) -> dict[str, Any]:
        """Regenerate the selected session summary through the metadata service."""
        info = require_session(self.get_system(ISessionManager), session_id)
        if info.loop_type == Loop.colloquy:
            logger.warning("Regenerate summary rejected (colloquy) | session=%s", session_id)
            raise business_http_error(403, GatewayErrorCode.COLLOQUY_OPERATION_FORBIDDEN, "Colloquy session cannot be manually compressed", details={"session_id": session_id})
        logger.info("Regenerate summary | session=%s", session_id)
        try:
            summary = await self.get_system(ISessionMetadataService).regenerate_summary(session_id)
        except (MetadataProfileUnavailableError, MetadataGenerationError) as exc:
            raise_metadata_http(exc)
        return {"success": True, "summary": summary, "session_id": session_id}
