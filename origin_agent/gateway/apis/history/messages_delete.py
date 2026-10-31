"""Delete complete logical rounds from History."""

import logging
from fastapi import APIRouter, Query
from entity.constant import GatewayErrorCode
from entity.puretype import SessionMessageDeletionResult
from gateway.api_support.sessions import require_idle_session_loop
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent
from interface.session_manager import ISessionManager

logger = logging.getLogger(__name__)


class DeleteHistoryMessagesAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/messages", self.handler, methods=["DELETE"], name="delete_session_messages", response_model_exclude_none=True)

    async def handler(self, session_id: str, count: int = Query(1, ge=1)) -> SessionMessageDeletionResult:
        """Delete the last count logical rounds, including following tool and assistant messages."""
        logger.info("Delete messages request | session=%s count=%d", session_id, count)
        loop = require_idle_session_loop(self.get_system(ISessionManager), session_id)
        result = loop.loop.delete_session_messages(count)
        if not result.deleted:
            raise business_http_error(400, GatewayErrorCode.MESSAGES_DELETE_REJECTED, result.error or "Messages deletion rejected", details={"session_id": session_id})
        result = result.model_copy(update={"history_count": loop.loop.history.count})
        logger.info("Delete messages result | session=%s count=%d deleted=%s remaining=%s", session_id, count, result.deleted, result.remaining_count)
        return result
