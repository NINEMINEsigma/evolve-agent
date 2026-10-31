"""Chat WebSocket connection lifecycle."""

import asyncio
import json
import logging
from urllib.parse import parse_qs
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, WebSocketException
from pydantic import ValidationError
from starlette.websockets import WebSocketState
from entity.constant import SESSIONS_DIR_NAME, WEBSOCKET_CLOSE_SESSION_DELETED
from entity.error import ApplicationStoppingError, LifecycleFailure, AgentspaceConnectionClosed
from entity.puretype import AgentspaceEvent, ClientInfo
from gateway.chat import Message, MessageType
from gateway.message_router import MessageRouter
from gateway.agentspace_event_bridge import attach_agentspace_events, detach_agentspace_events, is_connection_termination, requires_connection_eviction
from interface.api_component import APIComponent
from interface.agentspace_service import IAgentspaceService
from interface.approval_system import IApprovalSystem
from interface.frontend_sink import IFrontendSink
from interface.runtime_system import IRuntimeSystem
from interface.session_manager import ISessionManager

logger = logging.getLogger(__name__)


async def _send_approval_mode_state(ws: WebSocket, session_id: str) -> None:
    """Send the authoritative session approval mode to this connection."""
    from component.approval import ApprovalMode, get_approval_mode
    mode = get_approval_mode(session_id)
    await ws.send_text(Message(
        type=MessageType.HANDSFREE_MODE, session_id=session_id,
        handsfree_mode=mode == ApprovalMode.HANDSFREE, approval_mode=mode.value,
    ).model_dump_json(exclude_none=True))


async def _send_agentspace_ws_event(ws: WebSocket, session_id: str, event: AgentspaceEvent) -> None:
    """Serialize a typed Agentspace event at the WebSocket boundary."""
    await ws.send_text(Message(type=MessageType.AGENTSPACE_EVENT, session_id=session_id, agentspace_event=event).model_dump_json(exclude_none=True))


class ChatWebSocketAPI(APIComponent):
    def display(self, router: APIRouter) -> None:
        router.add_api_websocket_route("/ws/chat", self.handler, name="ws_chat")

    async def handler(self, ws: WebSocket) -> None:
        """Receive user messages, route them to Agent Loops and deliver replies."""
        gateway = self.gateway
        try:
            with gateway.admission.admit_connection():
                pass
        except ApplicationStoppingError:
            logger.info("WebSocket rejected (application shutting down)")
            raise WebSocketException(code=1001, reason="shutting_down")
        qs: dict[str, list[str]] = parse_qs(ws.scope.get("query_string", b"").decode())
        resume: str | None = qs.get("resume", [None])[0]
        conn_token: str | None = qs.get("conn_token", [None])[0]
        manager = self.get_system(ISessionManager)
        if resume:
            if manager.is_session_deleting(resume):
                logger.info("WebSocket rejected (session deleting) | session=%s", resume)
                raise WebSocketException(code=WEBSOCKET_CLOSE_SESSION_DELETED, reason="session_deleted")
            if not manager.exists(resume):
                manager.load_from_disk()
            if not manager.exists(resume) or manager.is_session_deleting(resume):
                logger.info("WebSocket rejected (session missing) | session=%s", resume)
                raise WebSocketException(code=WEBSOCKET_CLOSE_SESSION_DELETED, reason="session_deleted")
            sid = resume
        else:
            sid = manager.create()
        sink = self.get_system(IFrontendSink)
        if sink.is_session_occupied(sid, conn_token):
            logger.info("WebSocket rejected (session locked) | session=%s", sid)
            raise WebSocketException(code=4001, reason="session_locked")
        await ws.accept()
        if manager.is_session_deleting(sid) or not manager.exists(sid):
            logger.info("WebSocket closed after accept (session deleted) | session=%s", sid)
            await ws.close(code=WEBSOCKET_CLOSE_SESSION_DELETED, reason="session_deleted")
            return
        try:
            sink.register_ws(sid, ws, conn_token or "")
        except ApplicationStoppingError:
            await ws.close(code=1001, reason="shutting_down")
            return
        logger.info("WebSocket connected | session=%s", sid)
        agentspace_subscription_id: str | None = None
        agentspace_event_task: asyncio.Task[None] | None = None
        try:
            client_ip = ws.client.host if ws.client else ""
            if client_ip:
                existing = manager.get_client_info(sid)
                manager.set_client_info(sid, existing.model_copy(update={"client_ip": client_ip}) if existing else ClientInfo(client_ip=client_ip))
            manager.create_session(
                session_id=sid, frontend_sink=sink,
                history_store_dir=self.get_system(IRuntimeSystem).context.workspace / SESSIONS_DIR_NAME,
            )
            await ws.send_text(json.dumps(Message(type=MessageType.SYSTEM, session_id=sid, content="Connected to Evolve Agent").model_dump(exclude_none=True), ensure_ascii=False))
            build_hash: str = ws.app.state.build_hash
            if build_hash:
                await ws.send_text(json.dumps(Message(type=MessageType.SYSTEM, session_id=sid, content=json.dumps({"build_hash": build_hash})).model_dump(exclude_none=True), ensure_ascii=False))
            state = self.get_system(IApprovalSystem).backend_manager.get_state()
            await ws.send_text(Message(type=MessageType.SYSTEM, session_id=sid, content=json.dumps({"server_info": {
                "approval_model_name": state.profile_name or "", "approval_model_available": state.available,
            }})).model_dump_json(exclude_none=True))
            await _send_approval_mode_state(ws, sid)
            loop = manager.get_loop(sid)
            if loop is not None:
                agents_info: list[str] | None = None
                from entry.multi_agent_loop import MultiAgentLoop
                if isinstance(loop, MultiAgentLoop):
                    agents_info = list(loop.get_agents().keys())
                await ws.send_text(json.dumps(Message(
                    type=MessageType.HISTORY_SYNC, session_id=sid,
                    history_count=loop.loop.history.count, processing=loop.loop.is_active(),
                    token_usage=loop.get_token_usage(), context_tokens=loop.get_context_tokens(), agents=agents_info,
                ).model_dump(exclude_none=True), ensure_ascii=False))
            agentspace_service = self.get_system(IAgentspaceService)

            async def _send_current_agentspace_event(event: AgentspaceEvent) -> None:
                if ws.application_state is WebSocketState.DISCONNECTED:
                    raise AgentspaceConnectionClosed(f"agentspace connection closed | session={sid}")
                try:
                    await _send_agentspace_ws_event(ws, sid, event)
                except (WebSocketDisconnect, ConnectionResetError, BrokenPipeError) as exc:
                    raise AgentspaceConnectionClosed(f"agentspace send failed on closed connection | session={sid}") from exc
                except RuntimeError:
                    # 仅明确已断开时归为连接结束，其他内部错误保持传播。
                    if ws.application_state is not WebSocketState.DISCONNECTED:
                        raise
                    raise AgentspaceConnectionClosed(f"agentspace send raced with connection close | session={sid}")

            agentspace_subscription_id, agentspace_event_task = await attach_agentspace_events(
                agentspace_service, _send_current_agentspace_event, connection_label=conn_token or sid,
            )

            def _close_on_agentspace_failure(task: asyncio.Task[None]) -> None:
                if task.cancelled():
                    return
                failure = task.exception()
                if failure is None:
                    return
                # 先判慢消费者驱逐，再判连接终止，不能互换顺序。
                if requires_connection_eviction(failure):
                    try:
                        gateway.task_owner.mark_expected_failure(task)
                    except LifecycleFailure:
                        pass
                    logger.warning("Agentspace WebSocket send timeout; evicting slow connection | session=%s", sid)
                elif is_connection_termination(failure):
                    try:
                        gateway.task_owner.mark_expected_failure(task)
                    except LifecycleFailure:
                        pass
                    logger.info("Agentspace WebSocket peer disconnected | session=%s", sid)
                else:
                    logger.error("Agentspace WebSocket forwarding failed | session=%s", sid, exc_info=(type(failure), failure, failure.__traceback__))
                if ws.application_state is WebSocketState.DISCONNECTED:
                    return
                try:
                    gateway.spawn_work(ws.close(code=1011, reason="agentspace_event_forward_failed"), name=f"agentspace-ws-close-{sid[:8]}")
                except LifecycleFailure:
                    logger.info("Gateway closing; skip agentspace failure close | session=%s", sid)

            # 预期失败标记必须在Owner结算回调读取前执行。
            agentspace_event_task.add_done_callback(_close_on_agentspace_failure)
            gateway.task_owner.track(agentspace_event_task)
            message_router = MessageRouter(ws, sid, conn_token=conn_token or "")
            while True:
                raw = await ws.receive_text()
                try:
                    gateway.admission.require_open_connection()
                except ApplicationStoppingError:
                    await ws.close(code=1001, reason="shutting_down")
                    return
                try:
                    msg = Message.model_validate_json(raw)
                except ValidationError as exc:
                    await ws.send_text(json.dumps(Message(type=MessageType.ERROR, session_id=sid, message=f"Invalid message: {exc}").model_dump(exclude_none=True), ensure_ascii=False))
                    continue
                ok = await message_router.route(msg)
                if not ok:
                    return
                sid = message_router.sid
        except (WebSocketDisconnect, AgentspaceConnectionClosed):
            logger.info("WebSocket disconnected | session=%s", sid)
        except asyncio.CancelledError:
            logger.debug("WebSocket handler cancelled for session=%s (server shutting down)", sid)
            raise
        finally:
            try:
                await detach_agentspace_events(self.get_system(IAgentspaceService), agentspace_subscription_id, agentspace_event_task)
            finally:
                sink = self.get_system(IFrontendSink)
                # 旧连接不得释放已接管的新连接及其交互。
                if sink.get_ws(sid) is ws:
                    sink.unregister_ws(sid)
