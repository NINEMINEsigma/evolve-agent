"""Manual session title update."""

import logging
from typing import Any
from fastapi import APIRouter
from entity.puretype import SessionTitleUpdateRequest
from gateway.api_support.sessions import require_session
from interface.api_component import APIComponent
from interface.session_manager import ISessionManager

logger = logging.getLogger(__name__)


class UpdateSessionTitleAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/title", self.handler, methods=["PUT"], name="update_session_title")

    async def handler(self, session_id: str, payload: SessionTitleUpdateRequest) -> dict[str, Any]:
        """Rename a session manually."""
        manager = self.get_system(ISessionManager)
        require_session(manager, session_id)
        title = payload.title.strip()[:50]
        manager.update_title(session_id, title)
        logger.info("Update title | session=%s title=%s", session_id, title)
        return {"updated": True, "session_id": session_id, "title": title}
