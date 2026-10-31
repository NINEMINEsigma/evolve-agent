"""Session tag mutation."""

import logging
from typing import Any
from fastapi import APIRouter
from entity.constant import GatewayErrorCode
from entity.puretype import SessionTagsUpdateRequest
from gateway.api_support.sessions import require_session
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent
from interface.session_manager import ISessionManager

logger = logging.getLogger(__name__)


class UpdateSessionTagsAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/tags", self.handler, methods=["PUT"], name="update_session_tags")

    async def handler(self, session_id: str, payload: SessionTagsUpdateRequest) -> dict[str, Any]:
        """Update session tags without accepting a partially valid list."""
        manager = self.get_system(ISessionManager)
        require_session(manager, session_id)
        tags = [tag.strip() for tag in payload.tags]
        if any(not manager.chat_manager.validate_tag(tag) for tag in tags):
            raise business_http_error(400, GatewayErrorCode.INVALID_TAGS, "Invalid session tags")
        valid = manager.set_session_tags(session_id, tags)
        logger.info("Update tags | session=%s tags=%s", session_id, valid)
        return {"updated": True, "session_id": session_id, "tags": valid}


api = UpdateSessionTagsAPI()
