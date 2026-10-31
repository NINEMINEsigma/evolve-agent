"""Read-only offline session snapshot."""

from fastapi import APIRouter, Request
from fastapi.responses import Response
from entity.error import SessionExportError
from gateway.api_support.session_export import run_export_http
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent


class SessionExportSnapshotAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/export/snapshot", self.handler, methods=["POST"], name="capture_session_export")

    async def handler(self, session_id: str, req: Request) -> Response:
        """Capture the complete main session without reusing frontend pages."""
        gateway = self.gateway

        async def capture_response() -> Response:
            snapshot = await gateway.session_exports.capture(session_id)
            content = await gateway.session_exports.encode_snapshot(snapshot)
            return Response(content, media_type="application/json", headers={"Cache-Control": "no-store"})

        try:
            return await run_export_http(req, gateway, capture_response, f"session-export-snapshot:{session_id}")
        except SessionExportError as exc:
            raise business_http_error(exc.status, exc.code, str(exc)) from exc
