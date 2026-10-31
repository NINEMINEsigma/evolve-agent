"""Regenerate one user response with committed trim notification."""

import json
import logging
from typing import Any
from fastapi import APIRouter
from entity.constant import GatewayErrorCode
from entity.error import ProfileNotFoundError
from entity.puretype import MainSessionActivitySource, SessionRegenerateRequest
from gateway.chat import Message, MessageType
from gateway.api_support.sessions import require_idle_session_loop, require_session_loop
from gateway.http_boundary import business_http_error, require_business_http
from gateway.notifications import send_optional_ws_message
from interface.api_component import APIComponent
from interface.frontend_sink import IFrontendSink
from interface.llm_profile_store import ILLMProfileStore
from interface.session_manager import ISessionManager

logger = logging.getLogger(__name__)


class RegenerateResponseAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/regenerate", self.handler, methods=["POST"], name="regenerate_response")

    async def handler(self, session_id: str, payload: SessionRegenerateRequest) -> dict[str, Any]:
        """Trim History, refresh extension blocks and process the selected user message again."""
        logger.info("Regenerate request | session=%s", session_id)
        manager = self.get_system(ISessionManager)
        loop = require_idle_session_loop(manager, session_id)
        profile_store = self.get_system(ILLMProfileStore)
        require_business_http(self.gateway.admission)
        loop = require_idle_session_loop(manager, session_id)
        with profile_store.locked():
            try:
                profile = profile_store.resolve_profile_name(payload.llm_profile_name)
            except ProfileNotFoundError as exc:
                raise business_http_error(404, GatewayErrorCode.PROFILE_NOT_FOUND, str(exc)) from exc
            loop.set_profile(profile)
        activity_id = loop.loop.ensure_main_session_activity(
            MainSessionActivitySource.regenerate, character_name=loop.current_character_agent,
        )
        try:
            result = loop.loop.regenerate_response(payload.message_index)
            if not result.regenerate:
                raise business_http_error(400, GatewayErrorCode.REGENERATE_REJECTED, result.error or "Regeneration rejected", details={"session_id": session_id, "message_index": payload.message_index})
            ws = self.get_system(IFrontendSink).get_ws(session_id)
            if ws:
                await send_optional_ws_message(ws, Message(
                    type=MessageType.SYSTEM, session_id=session_id,
                    content=json.dumps({
                        "regenerate_trim": True, "keep_count": result.remaining_count,
                        "message_index": result.message_index, "message_suffix": result.message_suffix,
                        "dynamic_message_suffix": result.dynamic_message_suffix,
                    }),
                ))
            require_business_http(self.gateway.admission)
            require_session_loop(manager, session_id)
            reply = await loop.loop.process_message(
                result.last_user_content, skip_append=True,
                visible_characters=result.visible_characters,
                response_characters=result.response_characters,
                activity_source=MainSessionActivitySource.regenerate, activity_id=activity_id,
                input_sequences=[], require_tool_call=payload.require_tool_call,
            )
        finally:
            loop.loop.finish_main_session_activity(activity_id)
        sink = self.get_system(IFrontendSink)
        if reply:
            await sink.emit_assistant_message(session_id, reply, loop.current_character_agent)
        if ws:
            await send_optional_ws_message(ws, Message(
                type=MessageType.HISTORY_SYNC, session_id=session_id,
                history_count=loop.loop.history.count, processing=loop.loop.is_active(),
                token_usage=loop.get_token_usage(), context_tokens=loop.get_context_tokens(),
            ))
        logger.info("Regenerate ok | session=%s", session_id)
        return {"regenerate": True, "session_id": session_id, "history_count": loop.loop.history.count}


api = RegenerateResponseAPI()
