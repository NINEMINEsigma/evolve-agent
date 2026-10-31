"""Single original media preview."""

from urllib.parse import urlsplit
from fastapi import APIRouter, Path
from fastapi.responses import RedirectResponse, Response
from entity.constant import GatewayErrorCode, SESSION_MEDIA_ID_PATTERN
from entity.messages import ImageBlock, VideoBlock
from entity.error import HistoryMediaNotFoundError, HistoryMediaPreviewError
from entry.history_media import decode_media_preview
from gateway.api_support.media import require_media_loop
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent
from interface.session_manager import ISessionManager


class HistoryMediaContentAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/history/media/{media_id}/content", self.handler, methods=["GET"], name="get_session_media_content")

    async def handler(self, session_id: str, media_id: str = Path(pattern=SESSION_MEDIA_ID_PATTERN)) -> Response:
        loop = require_media_loop(self.get_system(ISessionManager), session_id, writable=False)
        try:
            block = loop.loop.get_session_media_block(media_id)
            headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
            if isinstance(block, (ImageBlock, VideoBlock)):
                url = block.image_url if isinstance(block, ImageBlock) else block.video_url
                if not url.startswith("data:"):
                    parsed = urlsplit(url)
                    if parsed.scheme not in ("http", "https") or not parsed.netloc:
                        raise HistoryMediaPreviewError("Media preview URL is not supported", 415)
                    return RedirectResponse(url=url, status_code=307, headers=headers)
            content, mime_type = decode_media_preview(block)
            if mime_type == "image/svg+xml":
                headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
            return Response(content=content, media_type=mime_type, headers=headers)
        except HistoryMediaNotFoundError as exc:
            raise business_http_error(404, GatewayErrorCode.MEDIA_NOT_FOUND, str(exc), details={"media_id": media_id}) from exc
        except HistoryMediaPreviewError as exc:
            code = GatewayErrorCode.MEDIA_PREVIEW_UNSUPPORTED if exc.status_code == 415 else GatewayErrorCode.MEDIA_PREVIEW_INVALID
            raise business_http_error(exc.status_code, code, str(exc), details={"media_id": media_id}) from exc
