"""Permanent session deletion with complete request ownership."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from fastapi import APIRouter
from entity.constant import GatewayErrorCode, WEBSOCKET_CLOSE_SESSION_DELETED
from entity.error import LifecycleFailure, SessionFileChangesBusyError
from entity.puretype import Loop
from gateway.http_boundary import business_http_error, require_business_http
from interface.api_component import APIComponent
from interface.agentspace_service import IAgentspaceService
from interface.frontend_sink import IFrontendSink
from interface.session_manager import ISessionManager
from interface.subagent_orchestrator import ISubAgentOrchestrator
from system.session_file_changes import SessionFileChangeStore

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _file_changes_delete_scope(
    session_id: str, manager: ISessionManager, store: SessionFileChangeStore,
) -> AsyncIterator[None]:
    # REQUEST所有者保留本作用域及真实线程结果，必要清理不能被取消遗失。
    block = asyncio.create_task(asyncio.to_thread(store.block_session, session_id))
    original: BaseException | None = None
    try:
        await asyncio.shield(block)
        yield
    except BaseException as exc:
        original = exc
        raise
    finally:
        errors: list[BaseException] = []
        try:
            await asyncio.shield(block)
        except BaseException as exc:
            if exc is not original:
                errors.append(exc)
        else:
            action = store.unblock_session if manager.exists(session_id) else store.forget_session
            cleanup = asyncio.create_task(asyncio.to_thread(action, session_id))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await asyncio.shield(cleanup)
                raise
            except Exception as exc:
                failure = LifecycleFailure("Session file changes deletion cleanup failed")
                failure.__cause__ = exc
                errors.append(failure)
        if errors:
            if original is not None:
                errors.insert(0, original)
            raise BaseExceptionGroup("Session deletion and file changes cleanup failed", errors)


class DeleteSessionAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_route("/api/sessions/{session_id}", self.handler, methods=["DELETE"], name="delete_session")

    async def handler(self, session_id: str) -> dict[str, Any]:
        """Permanently delete a session under Gateway request ownership."""
        gateway = self.gateway
        require_business_http(gateway.admission)
        try:
            return await gateway.task_owner.run_request(
                lambda: self._delete_session_impl(session_id),
                name=f"delete-session-{session_id}", admission=gateway.admission.admit_business,
            )
        except SessionFileChangesBusyError as exc:
            raise business_http_error(409, GatewayErrorCode.FILE_CHANGES_BUSY, str(exc), details={"session_id": session_id}) from exc

    async def _delete_session_impl(self, session_id: str) -> dict[str, Any]:
        manager = self.get_system(ISessionManager)
        info = manager.get(session_id)
        if info is None:
            logger.warning("Delete session rejected (not found) | session=%s", session_id)
            raise business_http_error(404, GatewayErrorCode.SESSION_NOT_FOUND, "Session not found", details={"session_id": session_id})
        if info.loop_type == Loop.colloquy:
            logger.warning("Delete session rejected (colloquy) | session=%s", session_id)
            raise business_http_error(403, GatewayErrorCode.COLLOQUY_OPERATION_FORBIDDEN, "Colloquy session cannot be deleted", details={"session_id": session_id})
        if not manager.begin_session_delete(session_id):
            logger.warning("Delete session rejected (already deleting) | session=%s", session_id)
            raise business_http_error(409, GatewayErrorCode.SESSION_DELETING, "Session deletion already in progress", details={"session_id": session_id})
        logger.info("Delete session | session=%s", session_id)
        try:
            store = self.get_system(IAgentspaceService).file_changes
            async with _file_changes_delete_scope(session_id, manager, store):
                await self.get_system(IFrontendSink).close_session(
                    session_id, code=WEBSOCKET_CLOSE_SESSION_DELETED, reason="session_deleted",
                )
                # 子Agent停止失败直接阻止后续删除。
                await self.get_system(ISubAgentOrchestrator).shutdown(session_id)
                await manager.delete_session_runtime(session_id)
                manager.remove(session_id)
                from gateway.session_cleanup import cleanup_session_resources
                await cleanup_session_resources(session_id)
        finally:
            manager.end_session_delete(session_id)
        logger.info("Delete session ok | session=%s", session_id)
        return {"deleted": True, "session_id": session_id}


api = DeleteSessionAPI()
