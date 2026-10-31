"""Public local font serving."""

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, Response
from entity.constant import HTTP_NO_CACHE_HEADERS, LOCAL_FONT_HTTP_PREFIX, LOCAL_FONT_MIME_TYPES
from entity.error import LocalFontAccessError
from interface.api_component import APIComponent
from util.local_fonts import resolve_local_font


class ServeLocalFontAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route(LOCAL_FONT_HTTP_PREFIX + "/{font_path:path}", self.handler, methods=["GET"], name="serve_local_font")

    async def handler(self, font_path: str) -> Response:
        """Serve a local woff2/woff/ttf/otf font for CSS font-face.

        Shared validation rejects traversal and enforces the existing byte limit.
        The response retains no-cache and cross-origin font access headers.
        """
        try:
            font_file = resolve_local_font(font_path)
        except LocalFontAccessError as exc:
            return HTMLResponse(str(exc), status_code=exc.status)
        media_type = LOCAL_FONT_MIME_TYPES.get(font_file.suffix.lower(), "application/octet-stream")
        return FileResponse(str(font_file), media_type=media_type, headers={**HTTP_NO_CACHE_HEADERS, "Access-Control-Allow-Origin": "*"})
