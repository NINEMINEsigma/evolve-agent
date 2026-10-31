"""Resume the tool loop from current History."""

import logging
from typing import Any
from fastapi import APIRouter
from gateway.chat import Message, MessageType
from gateway.api_support.sessions import require_idle_session_loop
from gateway.notifications import send_optional_ws_message
from interface.api_component import APIComponent
from interface.frontend_sink import IFrontendSink
from interface.session_manager import ISessionManager

logger = logging.getLogger(__name__)


class ResumeSessionAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/resume", self.handler, methods=["POST"], name="resume_session_endpoint")

    async def handler(self, session_id: str) -> dict[str, Any]:
        """Resume tool execution, clearing interruption and resetting the tool count.

        No user message is appended and History is not trimmed.
        """
        loop = require_idle_session_loop(self.get_system(ISessionManager), session_id)
        reply = await loop.resume()
        logger.info("Resume ok | session=%s reply_len=%d", session_id, len(reply))
        ws = self.get_system(IFrontendSink).get_ws(session_id)
        if ws:
            await send_optional_ws_message(ws, Message(
                type=MessageType.HISTORY_SYNC, session_id=session_id,
                history_count=loop.loop.history.count, processing=loop.loop.is_active(),
                token_usage=loop.get_token_usage(), context_tokens=loop.get_context_tokens(),
            ))
        return {"resumed": True, "session_id": session_id, "history_count": loop.loop.history.count}
