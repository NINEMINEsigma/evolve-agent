"""HTTP confirmation response."""

import logging
from typing import Any
from fastapi import APIRouter
from entity.constant import GatewayErrorCode
from entity.puretype import ConfirmResponseRequest
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent
from interface.frontend_sink import IFrontendSink

logger = logging.getLogger(__name__)


class ConfirmResponseAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/confirm/{request_id}", self.handler, methods=["POST"], name="http_confirm")

    async def handler(self, request_id: str, payload: ConfirmResponseRequest) -> dict[str, Any]:
        """Resolve confirmation independently of the WebSocket connection."""
        action = payload.action
        deny_reason = (payload.deny_reason or None) if action == "deny" else None
        sink = self.get_system(IFrontendSink)
        if not sink.resolve_confirm(request_id, action, deny_reason=deny_reason, denied_by=payload.denied_by):
            raise business_http_error(404, GatewayErrorCode.INTERACTION_NOT_FOUND, "Interaction not found or already answered", details={"request_id": request_id})
        logger.info("HTTP confirm | request_id=%s action=%s denied_by=%s", request_id, action, payload.denied_by)
        return {"resolved": True, "request_id": request_id, "action": action}


api = ConfirmResponseAPI()
