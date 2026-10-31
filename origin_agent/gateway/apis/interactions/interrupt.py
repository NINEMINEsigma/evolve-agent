"""Authoritative main-session interruption."""

import logging
from typing import Any
from fastapi import APIRouter
from entity.constant import GatewayErrorCode
from gateway.api_support.sessions import require_session_loop
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent
from interface.session_manager import ISessionManager

logger = logging.getLogger(__name__)


class InterruptSessionAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/interrupt/{session_id}", self.handler, methods=["POST"], name="http_interrupt")

    async def handler(self, session_id: str) -> dict[str, Any]:
        """Interrupt the registered active round and return its authoritative result.

        Idle sessions succeed; active rounds await bounded cancellation completion.
        """
        logger.info("HTTP interrupt | session=%s", session_id)
        loop = require_session_loop(self.get_system(ISessionManager), session_id)
        result = await loop.request_interrupt(reason="user")
        logger.info("HTTP interrupt result | session=%s status=%s", session_id, result.status)
        payload = result.model_dump()
        payload["interrupted"] = result.status in ("idle", "cancelled")
        if result.status == "timeout":
            raise business_http_error(409, GatewayErrorCode.INTERRUPT_TIMEOUT, "Session interruption timed out", details={"result": payload})
        if result.status == "failed":
            raise business_http_error(500, GatewayErrorCode.INTERRUPT_FAILED, "Session interruption failed", details={"result": payload})
        return payload


api = InterruptSessionAPI()
