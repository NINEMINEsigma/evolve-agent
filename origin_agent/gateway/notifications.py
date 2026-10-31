"""Optional WebSocket notifications shared outside endpoint implementations."""

import json
import logging

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from entity.puretype import Message, MessageType, SubAgentUpdate
from interface.frontend_sink import IFrontendSink

logger = logging.getLogger(__name__)


async def send_optional_ws_message(ws: WebSocket, message: Message) -> None:
    payload = message.model_dump_json(exclude_none=True)
    if ws.application_state is WebSocketState.DISCONNECTED:
        return
    try:
        await ws.send_text(payload)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected during notification | session=%s", message.session_id)


async def push_subagent_update(parent_session_id: str, update: SubAgentUpdate) -> None:
    from system.application import Application

    ws = Application.current().get_system(IFrontendSink).get_ws(parent_session_id)
    if ws is None:
        return
    await send_optional_ws_message(ws, Message(
        type=MessageType.SUBAGENT_UPDATE,
        session_id=parent_session_id,
        result=json.dumps({
            **update.model_dump(mode="json", exclude={"removed"}),
            "_removed": update.removed,
        }, ensure_ascii=False),
    ))
