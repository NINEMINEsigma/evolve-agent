"""Generate and save a session title."""

import logging
from typing import Any
from fastapi import APIRouter
from entity.error import MetadataProfileUnavailableError, MetadataGenerationError
from gateway.api_support.domain_errors import raise_metadata_http
from gateway.api_support.sessions import require_session
from gateway.http_boundary import require_business_http
from interface.api_component import APIComponent
from interface.session_manager import ISessionManager
from interface.session_metadata_service import ISessionMetadataService

logger = logging.getLogger(__name__)


class AutoTitleSessionAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/auto-title", self.handler, methods=["POST"], name="auto_title_session")

    async def handler(self, session_id: str) -> dict[str, Any]:
        """Generate and save a title with the global metadata service."""
        manager = self.get_system(ISessionManager)
        require_session(manager, session_id)
        try:
            title = await self.get_system(ISessionMetadataService).generate_title(session_id)
        except (MetadataProfileUnavailableError, MetadataGenerationError) as exc:
            raise_metadata_http(exc)
        require_business_http(self.gateway.admission)
        require_session(manager, session_id)
        manager.update_title(session_id, title)
        logger.info("Auto title | session=%s title=%s", session_id, title)
        return {"title": title, "session_id": session_id}
