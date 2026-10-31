"""Session preconditions shared by HTTP endpoints; never create a Loop."""

from entity.constant import GatewayErrorCode
from entity.puretype import SessionInfo, SessionStatus
from entry.base_agent_loop import IMainSessionLoop
from gateway.http_boundary import business_http_error
from interface.session_manager import ISessionManager


def require_session(manager: ISessionManager, session_id: str) -> SessionInfo:
    info = manager.get(session_id)
    if info is None or manager.is_session_deleting(session_id):
        raise business_http_error(
            404, GatewayErrorCode.SESSION_NOT_FOUND, "Session not found",
            details={"session_id": session_id},
        )
    return info


def require_writable_session(manager: ISessionManager, session_id: str) -> SessionInfo:
    info = require_session(manager, session_id)
    if info.status == SessionStatus.archived:
        raise business_http_error(
            403, GatewayErrorCode.SESSION_ARCHIVED, "Archived session cannot be changed",
            details={"session_id": session_id},
        )
    return info


def require_session_loop(manager: ISessionManager, session_id: str) -> IMainSessionLoop:
    require_session(manager, session_id)
    loop = manager.get_loop(session_id)
    if loop is None:
        raise business_http_error(
            409, GatewayErrorCode.SESSION_NOT_READY, "Session connection is not ready",
            details={"session_id": session_id},
        )
    if loop.loop.session_id != session_id:
        raise business_http_error(
            409, GatewayErrorCode.SESSION_ROTATING, "Session is rotating; refresh the current session",
            details={"session_id": session_id},
        )
    return loop


def require_idle_session_loop(manager: ISessionManager, session_id: str) -> IMainSessionLoop:
    require_writable_session(manager, session_id)
    loop = require_session_loop(manager, session_id)
    if loop.loop.is_active():
        raise business_http_error(
            409, GatewayErrorCode.SESSION_BUSY, "Session is processing",
            details={"session_id": session_id},
        )
    return loop


def validate_merge_sources(manager: ISessionManager, sources: list[str]) -> None:
    for source_id in sources:
        info = require_session(manager, source_id)
        if info.status != SessionStatus.archived:
            raise business_http_error(
                409, GatewayErrorCode.MERGE_SOURCE_NOT_ARCHIVED,
                "Source session must be archived",
                details={"source_id": source_id},
            )
