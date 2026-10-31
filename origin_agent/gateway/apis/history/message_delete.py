"""Delete one message in the last round with paired calls/results."""

import logging
from fastapi import APIRouter, Query
from entity.constant import GatewayErrorCode
from entity.puretype import SessionMessageDeletionResult
from gateway.api_support.sessions import require_idle_session_loop
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent
from interface.session_manager import ISessionManager

logger = logging.getLogger(__name__)


class DeleteHistoryMessageAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/messages/single", self.handler, methods=["DELETE"], name="delete_single_message", response_model_exclude_none=True)

    async def handler(self, session_id: str, index: int = Query(..., ge=0)) -> SessionMessageDeletionResult:
        """Delete one message in the last round, including paired cleanup."""
        logger.info("Delete single message request | session=%s index=%d", session_id, index)
        loop = require_idle_session_loop(self.get_system(ISessionManager), session_id)
        result = loop.loop.delete_single_message(index)
        if not result.deleted:
            raise business_http_error(400, GatewayErrorCode.MESSAGE_DELETE_REJECTED, result.error or "Message deletion rejected", details={"session_id": session_id, "message_index": index})
        result = result.model_copy(update={
            "token_usage": loop.get_token_usage(), "context_tokens": loop.get_context_tokens(),
            "history_count": loop.loop.history.count,
        })
        logger.info("Delete single message result | session=%s index=%d deleted=%s remaining=%s", session_id, index, result.deleted, result.remaining_count)
        return result


api = DeleteHistoryMessageAPI()
