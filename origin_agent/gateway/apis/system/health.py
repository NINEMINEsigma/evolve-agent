"""Gateway health endpoint."""

from typing import Any
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from interface.api_component import APIComponent
from interface.session_manager import ISessionManager


class HealthAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/health", self.handler, methods=["GET"], name="health")

    async def handler(self) -> Any:
        """Report serving state without creating sessions or Loops."""
        serving = self.gateway.admission.is_serving()
        payload: dict[str, object] = {"sessions": self.get_system(ISessionManager).count, "serving": serving}
        if serving:
            payload["status"] = "ok"
            return payload
        return JSONResponse({"status": "shutting_down", **payload}, status_code=503)
