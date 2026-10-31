"""Offline viewer build assets."""

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response
from entity.constant import GatewayErrorCode, SESSION_EXPORT_VIEWER_ASSETS, SESSION_EXPORT_VIEWER_MAX_BYTES
from gateway.frontend_assets import frontend_dist
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent


class SessionExportViewerAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/session-export/viewer/{asset_name}", self.handler, methods=["GET"], name="get_session_export_viewer")

    async def handler(self, asset_name: str) -> Response:
        if asset_name not in SESSION_EXPORT_VIEWER_ASSETS:
            raise business_http_error(404, GatewayErrorCode.EXPORT_VIEWER_NOT_FOUND, "Unknown offline viewer asset")
        path = frontend_dist() / "export" / asset_name
        if not path.is_file():
            raise business_http_error(503, GatewayErrorCode.EXPORT_VIEWER_NOT_BUILT, "Offline viewer is not built")
        if path.stat().st_size > SESSION_EXPORT_VIEWER_MAX_BYTES:
            raise business_http_error(413, GatewayErrorCode.EXPORT_VIEWER_LIMIT, "Offline viewer exceeds byte budget")
        return FileResponse(str(path), media_type="text/javascript" if asset_name.endswith(".js") else "text/css", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


api = SessionExportViewerAPI()
