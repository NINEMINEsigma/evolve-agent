"""Frontend entry page."""

import logging
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response
from entity.constant import HTTP_NO_CACHE_HEADERS
from gateway.frontend_assets import frontend_dist
from interface.api_component import APIComponent

logger = logging.getLogger(__name__)


class IndexAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/", self.handler, methods=["GET"], name="index")

    async def handler(self) -> Response:
        """Return the built React frontend, or HTTP 500 when unavailable."""
        index_html = frontend_dist() / "index.html"
        if not index_html.exists():
            logger.error("Frontend not built: %s missing", index_html)
            return HTMLResponse("Frontend not built. Please run the build first.", status_code=500)
        return HTMLResponse(index_html.read_text(encoding="utf-8"), headers=dict(HTTP_NO_CACHE_HEADERS))
