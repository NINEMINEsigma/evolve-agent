"""Archived-session merge and single-source continuation."""

import logging
from typing import Any
from fastapi import APIRouter
from entity.constant import GatewayErrorCode
from entity.puretype import SessionMergeRequest
from gateway.api_support.sessions import validate_merge_sources
from gateway.http_boundary import business_http_error
from interface.api_component import APIComponent
from interface.session_manager import ISessionManager

logger = logging.getLogger(__name__)


class MergeSessionsAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/merge", self.handler, methods=["POST"], name="merge_sessions_endpoint")

    async def handler(self, payload: SessionMergeRequest) -> Any:
        """Merge archived source sessions, including a single-source branch."""
        sources = payload.sources
        logger.info("Merge sessions | sources=%s", sources)
        manager = self.get_system(ISessionManager)
        validate_merge_sources(manager, sources)
        for loop in manager.get_all_loops().values():
            result = await loop.loop.merge_sessions(sources)
            if not result.merged:
                raise business_http_error(409, GatewayErrorCode.SESSION_MERGE_REJECTED, result.error or "Session merge rejected", details={"sources": sources})
            return result
        raise business_http_error(409, GatewayErrorCode.SESSION_NOT_READY, "Session connection is not ready", details={"sources": sources})
