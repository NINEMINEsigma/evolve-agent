"""Bounded offline export resource read."""

from fastapi import APIRouter, Request
from fastapi.responses import Response
from entity.constant import SESSION_EXPORT_RESOURCE_BODY_MAX_BYTES, SESSION_EXPORT_DIGEST_HEADER, SESSION_EXPORT_IDENTITY_HEADER
from entity.error import SessionExportError
from entity.puretype import SessionExportResourceRequest
from gateway.api_support.session_export import read_export_body, parse_export_model, run_export_http
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent


class SessionExportResourceAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/export/resource", self.handler, methods=["POST"], name="read_session_export_resource")

    async def handler(self, session_id: str, req: Request) -> Response:
        gateway = self.gateway
        body = await read_export_body(req, gateway, SESSION_EXPORT_RESOURCE_BODY_MAX_BYTES)
        payload = parse_export_model(body, SessionExportResourceRequest)
        try:
            result = await run_export_http(req, gateway, lambda: gateway.session_exports.read_resource(session_id, payload), f"session-export-resource:{session_id}")
        except SessionExportError as exc:
            raise business_http_error(exc.status, exc.code, str(exc)) from exc
        if result.status != "saved":
            status_code = {"missing": 404, "denied": 403, "too_large": 413}[result.status]
            message = {"missing": "Export resource is missing", "denied": "Export resource access is denied", "too_large": "Export resource exceeds the byte budget"}[result.status]
            raise business_http_error(status_code, result.code, message, details={
                "source": result.proof.source.model_dump(mode="json"),
                "proof": result.proof.model_dump(mode="json"),
            }, headers={"Cache-Control": "no-store"})
        proof = result.proof
        digest, identity = proof.digest, proof.identity
        assert digest is not None and identity is not None, "Saved export proof lacks digest or identity"
        return Response(result.content, media_type=result.mime_type, headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            SESSION_EXPORT_DIGEST_HEADER: digest, SESSION_EXPORT_IDENTITY_HEADER: identity,
        })
