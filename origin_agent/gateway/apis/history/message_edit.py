"""Edit a historical message without regenerating."""

import logging
from fastapi import APIRouter, Path
from entity.constant import GatewayErrorCode
from entity.puretype import SessionMessageEditRequest, SessionMessageEditResult
from gateway.api_support.sessions import require_idle_session_loop
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent
from interface.session_manager import ISessionManager

logger = logging.getLogger(__name__)


class EditHistoryMessageAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/messages/{message_index}", self.handler, methods=["PUT"], name="update_session_message", response_model_exclude_none=True)

    async def handler(self, session_id: str, payload: SessionMessageEditRequest, message_index: int = Path(ge=0)) -> SessionMessageEditResult:
        """Edit message content or visible characters without regenerating a reply."""
        logger.info("Edit message request | session=%s index=%d", session_id, message_index)
        loop = require_idle_session_loop(self.get_system(ISessionManager), session_id)
        content = payload.content
        if isinstance(content, list):
            content = [block.model_dump(mode="json") for block in content]
        result = loop.loop.edit_session_message(message_index, content, payload.visible_characters)
        logger.info("Edit message result | session=%s index=%d updated=%s", session_id, message_index, result.updated)
        if not result.updated:
            raise business_http_error(400, GatewayErrorCode.MESSAGE_EDIT_REJECTED, result.error or "Message edit rejected", details={"session_id": session_id, "message_index": message_index})
        return result


api = EditHistoryMessageAPI()
