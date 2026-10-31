"""Atomic media sending preference update."""

from fastapi import APIRouter, Path, Response
from entity.constant import GatewayErrorCode, SESSION_MEDIA_ID_PATTERN
from entity.error import HistoryMediaConflictError, HistoryMediaNotFoundError
from entity.puretype import SessionMediaUpdateRequest, SessionMediaUpdateResponse
from gateway.api_support.media import require_media_loop
from gateway.http_boundary import business_http_error, require_business_http
from interface.api_component import APIComponent
from interface.session_manager import ISessionManager


class HistoryMediaUpdateAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}/history/media/{media_id}", self.handler, methods=["PUT"], name="update_session_media")

    async def handler(self, session_id: str, payload: SessionMediaUpdateRequest, response: Response, media_id: str = Path(pattern=SESSION_MEDIA_ID_PATTERN)) -> SessionMediaUpdateResponse:
        require_business_http(self.gateway.admission)
        loop = require_media_loop(self.get_system(ISessionManager), session_id, writable=True)
        response.headers["Cache-Control"] = "no-store"
        try:
            return loop.loop.set_session_media_enabled(media_id, payload.send_multimodal, payload.expected_send_multimodal)
        except HistoryMediaNotFoundError as exc:
            raise business_http_error(404, GatewayErrorCode.MEDIA_NOT_FOUND, str(exc), details={"media_id": media_id}) from exc
        except HistoryMediaConflictError as exc:
            raise business_http_error(409, GatewayErrorCode.MEDIA_CONFLICT, str(exc), details={"media_id": media_id}) from exc


api = HistoryMediaUpdateAPI()
