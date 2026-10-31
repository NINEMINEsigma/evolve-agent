"""Resolve the existing main Loop for History media operations."""

from entry.base_agent_loop import IMainSessionLoop
from interface.session_manager import ISessionManager

from .sessions import require_session_loop, require_writable_session


def require_media_loop(
    manager: ISessionManager, session_id: str, *, writable: bool,
) -> IMainSessionLoop:
    if writable:
        require_writable_session(manager, session_id)
    return require_session_loop(manager, session_id)
