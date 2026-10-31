"""Generate and save session tags."""

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


class AutoTagsSessionAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/auto-tags", self.handler, methods=["POST"], name="auto_tags_session")

    async def handler(self, session_id: str) -> dict[str, Any]:
        """Generate and save tags with the global metadata service."""
        manager = self.get_system(ISessionManager)
        require_session(manager, session_id)
        try:
            tags = await self.get_system(ISessionMetadataService).generate_tags(session_id, manager.get_all_tags())
        except (MetadataProfileUnavailableError, MetadataGenerationError) as exc:
            raise_metadata_http(exc)
        require_business_http(self.gateway.admission)
        require_session(manager, session_id)
        manager.set_session_tags(session_id, tags)
        logger.info("Auto tags | session=%s tags=%s", session_id, tags)
        return {"tags": tags, "session_id": session_id}


api = AutoTagsSessionAPI()
