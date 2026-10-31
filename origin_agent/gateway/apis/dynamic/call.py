"""Registered dynamic endpoint message delivery."""

import json
import logging
from fastapi import APIRouter
from fastapi.responses import Response
from entity.constant import GatewayErrorCode, SYSTEM_CHARACTER_NAME
from entity.puretype import DynamicEndpointRequest, MessageContent
from entry.agent_support.multimodal import validate_content_blocks
from gateway.api_support.sessions import require_session_loop
from gateway.http_boundary import business_http_error, raise_request_validation, require_business_http
from interface.api_component import APIComponent
from interface.dynamic_endpoint_system import IDynamicEndpointSystem
from interface.session_manager import ISessionManager

logger = logging.getLogger(__name__)


class DynamicEndpointAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/dynamic/{session_id}/{agent_name}/{endpoint_name}", self.handler, methods=["POST"], name="dynamic_endpoint_handler")

    async def handler(self, session_id: str, agent_name: str, endpoint_name: str, payload: DynamicEndpointRequest) -> Response:
        """Deliver a registered endpoint callback as an Agent-private system message.

        Content accepts text or ordered multimodal blocks, and takes precedence over
        message; empty arrays and blank text fall back to message. Blocks retain
        their order behind a separate endpoint-prefix text block. Invalid media
        fields are rejected with standard 422 before queue acceptance.
        """
        raw_content = payload.content
        raw_blocks = None
        if isinstance(raw_content, list):
            raw_blocks = [block.model_dump(mode="json") for block in raw_content]
            error = validate_content_blocks(raw_blocks)
            if error is not None:
                raise_request_validation(error, location=("body", "content"))
        info = self.get_system(IDynamicEndpointSystem).lookup_endpoint(endpoint_name)
        if info is None or info.session_id != session_id or info.agent_name != agent_name:
            if info is not None:
                logger.warning("Dynamic endpoint mismatch | endpoint=%s expected sid=%s agent=%s got sid=%s agent=%s", endpoint_name, info.session_id, info.agent_name, session_id, agent_name)
            raise business_http_error(404, GatewayErrorCode.DYNAMIC_ENDPOINT_NOT_FOUND, "Dynamic endpoint not found", details={"endpoint_name": endpoint_name})
        message = payload.message
        content: MessageContent
        used: str
        if isinstance(raw_content, list):
            if not raw_content:
                content = f"[dynamic-endpoint] {endpoint_name}\n{message}"
                used = "message"
            else:
                assert raw_blocks is not None
                content = [{"type": "text", "text": f"[dynamic-endpoint] {endpoint_name}\n"}] + raw_blocks
                used = "content"
                logger.info("Dynamic endpoint content blocks | endpoint=%s types=%s", endpoint_name, [block.type for block in raw_content])
        elif isinstance(raw_content, str) and raw_content.strip():
            content = f"[dynamic-endpoint] {endpoint_name}\n{raw_content}"
            used = "content"
        else:
            content = f"[dynamic-endpoint] {endpoint_name}\n{message}"
            used = "message"
        require_business_http(self.gateway.admission)
        loop = require_session_loop(self.get_system(ISessionManager), session_id)
        loop.loop.message_queue.push(
            content, character_name=SYSTEM_CHARACTER_NAME, source="dynamic-endpoint",
            visible_characters=[agent_name], response_characters=[agent_name],
        )
        logger.info("Dynamic endpoint triggered | endpoint=%s session=%s agent=%s used=%s", endpoint_name, session_id, agent_name, used)
        return Response(json.dumps({
            "delivered": True, "queued": True, "endpoint_name": endpoint_name,
            "session_id": session_id, "used": used,
        }, ensure_ascii=False), media_type="application/json", status_code=202)
