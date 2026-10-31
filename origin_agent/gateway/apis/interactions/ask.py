"""HTTP question response."""

import logging
from typing import Any
from fastapi import APIRouter
from entity.constant import GatewayErrorCode
from entity.puretype import AskResponseRequest
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent
from interface.frontend_sink import IFrontendSink

logger = logging.getLogger(__name__)


class AskResponseAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/ask/{request_id}", self.handler, methods=["POST"], name="http_ask")

    async def handler(self, request_id: str, payload: AskResponseRequest) -> dict[str, Any]:
        """Resolve a question independently of the WebSocket connection."""
        if not self.get_system(IFrontendSink).resolve_ask(request_id, answers=payload.answers):
            raise business_http_error(404, GatewayErrorCode.INTERACTION_NOT_FOUND, "Interaction not found or already answered", details={"request_id": request_id})
        logger.info("HTTP ask response | request_id=%s answers=%d", request_id, len(payload.answers or []))
        return {"resolved": True, "request_id": request_id, "answers": [answer.model_dump(exclude_none=True) for answer in (payload.answers or [])]}


api = AskResponseAPI()
