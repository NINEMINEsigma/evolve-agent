"""Frontend SPA fallback after explicit HTTP endpoints."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from entity.constant import (
    GatewayErrorCode, GATEWAY_API_FALLBACK_PRIORITY,
    GATEWAY_BUSINESS_HTTP_PREFIXES, HTTP_NO_CACHE_HEADERS,
)
from gateway.frontend_assets import frontend_dist, guess_media_type_with_charset
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent


class SpaFallbackAPI(APIComponent):
    priority = GATEWAY_API_FALLBACK_PRIORITY

    def display(self, router: APIRouter) -> None:
        router.add_api_route("/{full_path:path}", self.handler, methods=["GET"], name="spa_fallback")

    async def handler(self, full_path: str) -> Response:
        """Serve real dist files or the SPA entry after explicit API routes.

        Reserved business paths return structured 404 instead of a successful SPA.
        A missing frontend entry returns 404.
        """
        path = "/" + full_path
        if any(path == prefix or path.startswith(prefix + "/") for prefix in GATEWAY_BUSINESS_HTTP_PREFIXES):
            raise business_http_error(404, GatewayErrorCode.ROUTE_NOT_FOUND, f"Not found: {full_path}")
        dist = frontend_dist()
        candidate = dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate), media_type=guess_media_type_with_charset(candidate), headers=dict(HTTP_NO_CACHE_HEADERS))
        index_html = dist / "index.html"
        if index_html.exists():
            return HTMLResponse(index_html.read_text(encoding="utf-8"), headers=dict(HTTP_NO_CACHE_HEADERS))
        raise HTTPException(status_code=404, detail=f"Not found: {full_path}")


api = SpaFallbackAPI()
