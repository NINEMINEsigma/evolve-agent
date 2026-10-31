"""Manual Cron task trigger."""

import logging
from typing import Any
from fastapi import APIRouter
from entity.constant import GatewayErrorCode
from gateway.api_support.sessions import require_session
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent
from interface.cron_router import ICronRouter
from interface.session_manager import ISessionManager

logger = logging.getLogger(__name__)


class TriggerSessionCronTaskAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/cron-tasks/{task_id}/trigger", self.handler, methods=["POST"], name="trigger_cron_task_endpoint")

    async def handler(self, session_id: str, task_id: str) -> dict[str, Any]:
        """Trigger one execution of the selected scheduled task."""
        require_session(self.get_system(ISessionManager), session_id)
        logger.info("Trigger cron task | session=%s task_id=%s", session_id, task_id)
        result = self.get_system(ICronRouter).trigger_cron_task(session_id, task_id)
        if not result["success"]:
            raise business_http_error(404, GatewayErrorCode.CRON_TASK_NOT_FOUND, "Cron task not found", details={"session_id": session_id, "task_id": task_id})
        return result


api = TriggerSessionCronTaskAPI()
