"""Construct the Gateway HTTP application; endpoint components live in apis."""

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from gateway.frontend_assets import compute_build_hash, frontend_dist
from gateway.http_boundary import (
    GatewayAdmissionMiddleware, GatewayAPIRoute, handle_http_exception,
)
from interface.gateway_system import IGatewaySystem

logger = logging.getLogger(__name__)


def build_router_app(gateway: IGatewaySystem) -> FastAPI:
    """Build one application using its already-bound, not-yet-awake owner."""
    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        yield

    application = FastAPI(title="Evolve Agent Gateway", lifespan=lifespan)
    application.add_exception_handler(HTTPException, handle_http_exception)
    application.add_middleware(GatewayAdmissionMiddleware, admission=gateway.admission)
    router = APIRouter(route_class=GatewayAPIRoute)
    gateway.display_apis(router)
    application.include_router(router)
    application.state.build_hash = compute_build_hash()
    dist = frontend_dist()
    if dist.is_dir():
        assets_dir = dist / "assets"
        if assets_dir.is_dir():
            # 保留原include_router之后的挂载顺序与静态响应语义。
            application.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
        logger.info(
            "Frontend dist found at %s (build=%s)",
            dist, application.state.build_hash or "unknown",
        )
    return application
