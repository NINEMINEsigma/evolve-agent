"""Offline export consistency verification."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from entity.constant import SESSION_EXPORT_VERIFY_BODY_MAX_BYTES
from entity.error import SessionExportError
from entity.puretype import SessionExportVerifyRequest
from gateway.api_support.session_export import read_export_body, parse_export_model, run_export_http
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent


class SessionExportVerifyAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/export/verify", self.handler, methods=["POST"], name="verify_session_export")

    async def handler(self, session_id: str, req: Request) -> Response:
        gateway = self.gateway
        body = await read_export_body(req, gateway, SESSION_EXPORT_VERIFY_BODY_MAX_BYTES)
        payload = parse_export_model(body, SessionExportVerifyRequest)
        try:
            result = await run_export_http(req, gateway, lambda: gateway.session_exports.verify(session_id, payload), f"session-export-verify:{session_id}")
            return JSONResponse(result.model_dump(mode="json"), headers={"Cache-Control": "no-store"})
        except SessionExportError as exc:
            raise business_http_error(exc.status, exc.code, str(exc)) from exc
