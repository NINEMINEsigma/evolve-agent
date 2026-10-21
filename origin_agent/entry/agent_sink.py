"""Agent 交互实现 — 向上（用户/父Agent）通信的事件契约见 interface.agent_sink。

- FrontendSink：主 Agent 通过 WebSocket 与前端用户交互，槽位类型为 IFrontendSink
- ParentAgentSink：子 Agent 通过 outbox + orchestrator 与父 Agent 交互，类型为 IAgentSink
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from contextlib import contextmanager
from collections.abc import Iterator
from typing import * # type: ignore
from starlette.websockets import WebSocketDisconnect, WebSocketState
from entity.constant import (
    ApplicationState,
    SHUTDOWN_SEND_TIMEOUT_SECONDS,
    SYSTEM_QUIESCE_TIMEOUT_SECONDS,
    SYSTEM_CHARACTER_NAME,
)
from entity.puretype import (
    ApprovalProfileState,
    ApprovalResult,
    AskAnswerItem,
    HistoryUpdatedEvent,
    Message,
    MessageContent,
    MessageMetrics,
    MessageType,
    MetadataProfileState,
    ModalityProfileStates,
    StreamDeltaEvent,
    StreamDoneEvent,
    StreamEvent,
    ToolCallDelta,
    ToolCallRequest,
    ToolchainSummaryProfileState,
)
from framework import AsyncSystem
from system.lifecycle import ApplicationStoppingError, LifecycleFailure, TaskOwner
from interface.agent_sink import IAgentSink
from interface.frontend_sink import IFrontendSink
from interface.tool_registry import IToolRegistry
from interface.runtime_system import IRuntimeSystem

if TYPE_CHECKING:
    from fastapi import WebSocket
    from subagent.loop import SubAgentLoop

logger = logging.getLogger(__name__)


@dataclass
class WsConnectionEntry:
    """WebSocket 连接条目，附带 connection token 用于会话锁定。

    token 标识发起连接的标签页，用于区分刷新（同 token）与新标签页（不同 token）。
    """
    ws: "WebSocket"
    token: str
    connected_at: float


class FrontendSink(IFrontendSink):
    """主 Agent 的实现 — 通过 WebSocket 与前端用户通信。

    通过 IFrontendSink 同时满足 System 槽位与 IAgentSink 事件出口；依赖
    RuntimeSystem。发送与交互属有调用方等待的请求级操作，经
    TaskOwner.run_request 登记：新交互（审批/提问）只在 RUNNING 接收；
    既有结果与 History 回显在 STOPPING 仍允许到关闭输出，发送期限不超过
    SHUTDOWN_SEND_TIMEOUT_SECONDS。
    """

    def __init__(self) -> None:
        IFrontendSink.__init__(self, dependencies=(IRuntimeSystem,))
        # session_id → WsConnectionEntry
        self._ws_sinks: dict[str, WsConnectionEntry] = {}
        # {request_id: Future[ApprovalResult]}
        self._pending_confirms: dict[str, asyncio.Future] = {}
        # {request_id: session_id}
        self._confirm_session_map: dict[str, str] = {}
        # {request_id: Future[str]}
        self._pending_asks: dict[str, asyncio.Future] = {}
        # {request_id: session_id}
        self._ask_session_map: dict[str, str] = {}
        self._runtime: IRuntimeSystem
        self._requests: TaskOwner
        self._send_closed: bool = False
        self._interaction_closed: bool = False
        self._close_task: asyncio.Task[None] | None = None
        self._send_deadlines: set[asyncio.Timeout] = set()

    async def virtual_awake(self) -> None:
        self._runtime = self.get_system(IRuntimeSystem)
        self._requests = TaskOwner("FrontendSink", self._runtime.record_failure)

    # -- 接收边界 --

    def close_admission(self) -> None:
        """封闭新交互，并缩短在途发送期限；保留必要结果与History回显。"""
        self._interaction_closed = True
        deadline = asyncio.get_running_loop().time() + SHUTDOWN_SEND_TIMEOUT_SECONDS
        for scope in tuple(self._send_deadlines):
            if not scope.expired():
                current = scope.when()
                if current is None or current > deadline:
                    scope.reschedule(deadline)

    @contextmanager
    def _admit_interaction(self) -> Iterator[None]:
        with self._runtime.admission():
            if self._interaction_closed:
                raise ApplicationStoppingError("Frontend interaction admission is closed")
            yield

    @contextmanager
    def _admit_send(self) -> Iterator[None]:
        if self._send_closed:
            raise ApplicationStoppingError("Frontend output is closed")
        if self._runtime.state not in (ApplicationState.RUNNING, ApplicationState.STOPPING):
            raise LifecycleFailure("Frontend output requires a running or stopping application")
        yield

    async def _send_raw(self, ws: WebSocket, payload: str, session_id: str) -> bool:
        """仅转换明确断线或关闭发送超时；模型和内部错误向调用方传播。"""
        if ws.application_state == WebSocketState.DISCONNECTED:
            return False
        timeout = (
            SHUTDOWN_SEND_TIMEOUT_SECONDS
            if self._interaction_closed or self._runtime.state == ApplicationState.STOPPING
            else None
        )
        scope = asyncio.timeout(timeout)
        try:
            async with scope:
                self._send_deadlines.add(scope)
                await ws.send_text(payload)
            return True
        except (WebSocketDisconnect, ConnectionResetError, BrokenPipeError):
            logger.info("Frontend disconnected during send | session=%s", session_id)
            return False
        except TimeoutError:
            if not scope.expired():
                raise
            logger.warning("Frontend shutdown send timed out | session=%s", session_id)
            return False
        finally:
            self._send_deadlines.discard(scope)

    def cancel_pending_interactions(self) -> None:
        """同步解除所有待审批与提问 Future；关闭与连接移除时调用。"""
        self.close_admission()
        self._deny_all_confirms()
        self._deny_all_asks()

    # -- WebSocket 管理 --

    def register_ws(self, session_id: str, ws: WebSocket, token: str) -> None:
        import time
        with self._runtime.admission():
            if self._interaction_closed:
                raise ApplicationStoppingError("Frontend connection admission is closed")
            self._ws_sinks[session_id] = WsConnectionEntry(
                ws=ws, token=token, connected_at=time.time()
            )

    def unregister_ws(self, session_id: str) -> None:
        self._ws_sinks.pop(session_id, None)
        # 自动拒绝该 session 的所有待处理确认和提问
        self._deny_session_confirms(session_id)
        self._deny_session_asks(session_id)

    async def close_session(
        self, session_id: str, *, code: int, reason: str,
    ) -> bool:
        """使会话连接失效并关闭 WebSocket；无活动连接时保持幂等。

        永久删除会话仍使用 4004 语义：先移除映射并拒绝待处理交互，
        再以传入关闭码终止已建立连接。应用整体退出使用独立的
        close_all_connections 以标准 1001 关闭，不与此路径混用。
        """
        entry = self._ws_sinks.pop(session_id, None)
        self._deny_session_confirms(session_id)
        self._deny_session_asks(session_id)
        if entry is None:
            return False
        if entry.ws.application_state != WebSocketState.DISCONNECTED:
            try:
                async with asyncio.timeout(SYSTEM_QUIESCE_TIMEOUT_SECONDS):
                    await entry.ws.close(code=code, reason=reason)
            except (WebSocketDisconnect, ConnectionResetError, BrokenPipeError):
                logger.info("WebSocket already disconnected | session=%s", session_id)
        return True

    async def close_all_connections(self) -> None:
        """由应用协调任务调用；并发关闭等待同一实际关闭任务。"""
        if self._close_task is None:
            self.cancel_pending_interactions()
            self._send_closed = True
            self._close_task = asyncio.create_task(
                self._close_connections(), name="frontend-close-connections",
            )
        await asyncio.shield(self._close_task)

    async def _close_connections(self) -> None:
        failures: list[BaseException] = []
        try:
            await self._requests.cancel_and_wait(timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS)
        except BaseException as exc:
            if not self._requests.is_idle:
                raise
            failures.append(exc)
        for session_id, entry in tuple(self._ws_sinks.items()):
            try:
                if entry.ws.application_state != WebSocketState.DISCONNECTED:
                    async with asyncio.timeout(SYSTEM_QUIESCE_TIMEOUT_SECONDS):
                        await entry.ws.close(code=1001, reason="going_away")
            except (WebSocketDisconnect, ConnectionResetError, BrokenPipeError):
                pass
            except BaseException as exc:
                failures.append(exc)
                continue
            if self._ws_sinks.get(session_id) is entry:
                self._ws_sinks.pop(session_id)
        if failures:
            raise BaseExceptionGroup("Frontend connection cleanup failed", failures)

    def get_ws(self, session_id: str) -> WebSocket | None:
        entry = self._ws_sinks.get(session_id)
        return entry.ws if entry else None

    def get_all_ws(self) -> dict[str, WebSocket]:
        """返回所有已注册 WebSocket 的快照副本。"""
        return {sid: entry.ws for sid, entry in self._ws_sinks.items()}

    async def broadcast_profile_change(
        self,
        operation: str,
        old_name: str,
        new_name: str | None,
    ) -> list[str]:
        """向所有已连接前端广播独立的 Profile 变更事件。"""
        return await self._requests.run_request(
            lambda: self._broadcast_profile_change(operation, old_name, new_name),
            name="frontend-broadcast-profile-change",
            admission=self._admit_send,
            cancel_timeout=SHUTDOWN_SEND_TIMEOUT_SECONDS,
        )

    async def _broadcast_profile_change(
        self,
        operation: str,
        old_name: str,
        new_name: str | None,
    ) -> list[str]:
        failures: list[str] = []
        for session_id, ws in self.get_all_ws().items():
            message = Message(
                type=MessageType.LLM_PROFILE_CHANGED,
                session_id=session_id,
                operation=operation,
                old_name=old_name,
                new_name=new_name,
            )
            payload = message.model_dump(exclude_none=True)
            # 删除最后一个 Profile 时协议要求显式携带 JSON null。
            payload["new_name"] = new_name
            if not await self._send_raw(ws, json.dumps(payload, ensure_ascii=False), session_id):
                failures.append(session_id)
        return failures

    async def broadcast_approval_profile_change(
        self,
        state: ApprovalProfileState,
    ) -> list[str]:
        """向所有已连接前端广播审批 Profile 状态变更。

        ``state`` 为 ``ApprovalProfileState`` 实例。显式保留 null 值
        以便前端区分"未选择"与"字段缺失"；Profile 变化不携带审批模式。
        """
        return await self._requests.run_request(
            lambda: self._broadcast_approval_profile_change(state),
            name="frontend-broadcast-approval-profile-change",
            admission=self._admit_send,
            cancel_timeout=SHUTDOWN_SEND_TIMEOUT_SECONDS,
        )

    async def _broadcast_approval_profile_change(
        self,
        state: ApprovalProfileState,
    ) -> list[str]:
        failures: list[str] = []
        for session_id, ws in self.get_all_ws().items():
            message = Message(
                type=MessageType.APPROVAL_PROFILE_CHANGED,
                session_id=session_id,
                approval_profile_name=state.profile_name,
                approval_profile_model=state.model,
                approval_profile_available=state.available,
            )
            payload = message.model_dump(exclude_none=True)
            payload["approval_profile_name"] = state.profile_name
            payload["approval_profile_model"] = state.model
            if not await self._send_raw(ws, json.dumps(payload, ensure_ascii=False), session_id):
                failures.append(session_id)
        return failures

    async def broadcast_metadata_profile_change(
        self,
        state: MetadataProfileState,
    ) -> list[str]:
        """向所有已连接前端广播全局元数据 Profile 状态变更。"""
        return await self._requests.run_request(
            lambda: self._broadcast_metadata_profile_change(state),
            name="frontend-broadcast-metadata-profile-change",
            admission=self._admit_send,
            cancel_timeout=SHUTDOWN_SEND_TIMEOUT_SECONDS,
        )

    async def _broadcast_metadata_profile_change(
        self,
        state: MetadataProfileState,
    ) -> list[str]:
        failures: list[str] = []
        for session_id, ws in self.get_all_ws().items():
            message = Message(
                type=MessageType.METADATA_PROFILE_CHANGED,
                session_id=session_id,
                metadata_profile_name=state.profile_name,
                metadata_profile_model=state.model,
                metadata_profile_available=state.available,
            )
            payload = message.model_dump(exclude_none=True)
            payload["metadata_profile_name"] = state.profile_name
            payload["metadata_profile_model"] = state.model
            if not await self._send_raw(ws, json.dumps(payload, ensure_ascii=False), session_id):
                failures.append(session_id)
        return failures

    async def broadcast_toolchain_summary_profile_change(
        self,
        state: ToolchainSummaryProfileState,
    ) -> list[str]:
        """向所有已连接前端广播工具链摘要 Profile 状态变更。"""
        return await self._requests.run_request(
            lambda: self._broadcast_toolchain_summary_profile_change(state),
            name="frontend-broadcast-toolchain-summary-profile-change",
            admission=self._admit_send,
            cancel_timeout=SHUTDOWN_SEND_TIMEOUT_SECONDS,
        )

    async def _broadcast_toolchain_summary_profile_change(
        self,
        state: ToolchainSummaryProfileState,
    ) -> list[str]:
        failures: list[str] = []
        for session_id, ws in self.get_all_ws().items():
            message = Message(
                type=MessageType.TOOLCHAIN_SUMMARY_PROFILE_CHANGED,
                session_id=session_id,
                toolchain_summary_profile_name=state.profile_name,
                toolchain_summary_profile_model=state.model,
                toolchain_summary_profile_available=state.available,
            )
            payload = message.model_dump(exclude_none=True)
            payload["toolchain_summary_profile_name"] = state.profile_name
            payload["toolchain_summary_profile_model"] = state.model
            if not await self._send_raw(ws, json.dumps(payload, ensure_ascii=False), session_id):
                failures.append(session_id)
        return failures

    async def broadcast_modality_profile_change(
        self,
        states: ModalityProfileStates,
    ) -> list[str]:
        """向所有已连接前端广播三路全局多模态 Profile 状态。"""
        return await self._requests.run_request(
            lambda: self._broadcast_modality_profile_change(states),
            name="frontend-broadcast-modality-profile-change",
            admission=self._admit_send,
            cancel_timeout=SHUTDOWN_SEND_TIMEOUT_SECONDS,
        )

    async def _broadcast_modality_profile_change(
        self,
        states: ModalityProfileStates,
    ) -> list[str]:
        failures: list[str] = []
        for session_id, ws in self.get_all_ws().items():
            message = Message(
                type=MessageType.MODALITY_PROFILE_CHANGED,
                session_id=session_id,
                modality_vision_image_profile_name=states.image.profile_name,
                modality_vision_image_profile_model=states.image.model,
                modality_vision_image_profile_available=states.image.available,
                modality_audio_profile_name=states.audio.profile_name,
                modality_audio_profile_model=states.audio.model,
                modality_audio_profile_available=states.audio.available,
                modality_vision_video_profile_name=states.video.profile_name,
                modality_vision_video_profile_model=states.video.model,
                modality_vision_video_profile_available=states.video.available,
            )
            payload = message.model_dump(exclude_none=True)
            payload["modality_vision_image_profile_name"] = states.image.profile_name
            payload["modality_vision_image_profile_model"] = states.image.model
            payload["modality_audio_profile_name"] = states.audio.profile_name
            payload["modality_audio_profile_model"] = states.audio.model
            payload["modality_vision_video_profile_name"] = states.video.profile_name
            payload["modality_vision_video_profile_model"] = states.video.model
            if not await self._send_raw(ws, json.dumps(payload, ensure_ascii=False), session_id):
                failures.append(session_id)
        return failures

    def is_session_occupied(self, session_id: str, token: str | None) -> bool:
        """判断会话是否已被其他标签页占用。

        - 无条目 → 未占用
        - 条目存在但 WebSocket 已断开 → 清理并返回未占用
        - 条目存在且 token 匹配 → 未占用（同标签页刷新，可接管）
        - 条目存在且 token 不匹配且连接存活 → 已占用
        """
        entry = self._ws_sinks.get(session_id)
        if entry is None:
            return False
        from starlette.websockets import WebSocketState
        if entry.ws.client_state == WebSocketState.DISCONNECTED:
            self._ws_sinks.pop(session_id, None)
            return False
        if token and entry.token == token:
            return False
        return True

    # -- 审批请求 --

    async def request_approval(self, tool_name: str, args: dict,
                               reason: str = "", content: str = "",
                               session_id: str = "") -> ApprovalResult:
        """向 WebSocket 发送 confirm_request 并等待前端响应。"""
        from entity.puretype import ApprovalResult

        request_id: str = uuid.uuid4().hex[:8]
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        fut: asyncio.Future[ApprovalResult] = loop.create_future()
        self._pending_confirms[request_id] = fut
        self._confirm_session_map[request_id] = session_id

        ws = self.get_ws(session_id)
        if ws is None:
            self._pending_confirms.pop(request_id, None)
            self._confirm_session_map.pop(request_id, None)
            return ApprovalResult(action="deny", deny_reason="WebSocket not connected", denied_by=SYSTEM_CHARACTER_NAME)

        try:
            return await self._requests.run_request(
                lambda: self._request_approval(
                    ws, session_id, request_id, tool_name, args, reason, content, fut,
                ),
                name="frontend-request-approval",
                admission=self._admit_interaction,
            )
        except ApplicationStoppingError:
            self._pending_confirms.pop(request_id, None)
            self._confirm_session_map.pop(request_id, None)
            return ApprovalResult(action="deny", deny_reason="Application is stopping", denied_by=SYSTEM_CHARACTER_NAME)
        finally:
            self._pending_confirms.pop(request_id, None)
            self._confirm_session_map.pop(request_id, None)
            if not fut.done():
                fut.cancel()

    async def _request_approval(
        self,
        ws: WebSocket,
        session_id: str,
        request_id: str,
        tool_name: str,
        args: dict,
        reason: str,
        content: str,
        fut: asyncio.Future,
    ) -> ApprovalResult:
        from entity.puretype import ApprovalResult
        from system.application import Application
        tool_registry = Application.current().get_system(IToolRegistry)
        # 前端期望 request_id/tool/args/content 在消息顶层
        display_args = dict(args)
        if reason:
            display_args["reason"] = reason
        msg = Message(
            type=MessageType.CONFIRM_REQUEST,
            session_id=session_id,
            request_id=request_id,
            tool=tool_name,
            args=display_args,
            content=content,
            danger_level=str(tool_registry.get_danger_level(tool_name).value),
        )
        # 模型构造/序列化错误传播，不作为网络异常吞掉。
        payload = json.dumps(msg.model_dump(exclude_none=True), ensure_ascii=False)
        if not await self._send_raw(ws, payload, session_id):
            return ApprovalResult(
                action="deny", deny_reason="WebSocket disconnected during approval request",
                denied_by=SYSTEM_CHARACTER_NAME,
            )
        return await fut

    def resolve_confirm(self, request_id: str, action: str,
                        deny_reason: str | None = None,
                        denied_by: str = "user") -> bool:
        """解析前端发来的审批结果。"""
        logger.info("Resolve confirm | request_id=%s action=%s denied_by=%s", request_id, action, denied_by)
        from entity.puretype import ApprovalResult
        fut = self._pending_confirms.pop(request_id, None)
        self._confirm_session_map.pop(request_id, None)
        if fut and not fut.done():
            fut.set_result(ApprovalResult(action=action, deny_reason=deny_reason, denied_by=denied_by))
            logger.info("Resolve confirm ok | request_id=%s action=%s", request_id, action)
            return True
        logger.warning("Resolve confirm fail | request_id=%s (no pending future)", request_id)
        return False

    def _deny_session_confirms(self, session_id: str) -> None:
        from entity.puretype import ApprovalResult
        for rid in list(self._confirm_session_map.keys()):
            if self._confirm_session_map.get(rid) == session_id:
                self.resolve_confirm(rid, "deny", deny_reason="WebSocket disconnected", denied_by=SYSTEM_CHARACTER_NAME)

    def _deny_all_confirms(self) -> None:
        from entity.puretype import ApprovalResult
        for rid in list(self._pending_confirms.keys()):
            fut = self._pending_confirms.pop(rid, None)
            self._confirm_session_map.pop(rid, None)
            if fut is not None and not fut.done():
                fut.set_result(ApprovalResult(
                    action="deny", deny_reason="Application is stopping",
                    denied_by=SYSTEM_CHARACTER_NAME,
                ))

    # -- 提问请求 --

    async def ask_question(self, questions: list[dict], session_id: str = "") -> dict:
        """向 WebSocket 发送 ask_request（多问题表单）并等待前端响应。"""
        request_id: str = uuid.uuid4().hex[:8]
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self._pending_asks[request_id] = fut
        self._ask_session_map[request_id] = session_id

        ws = self.get_ws(session_id)
        if ws is None:
            self._pending_asks.pop(request_id, None)
            self._ask_session_map.pop(request_id, None)
            return {"error": "WebSocket connection unavailable, cannot send question"}

        try:
            return await self._requests.run_request(
                lambda: self._ask_question(
                    ws, session_id, request_id, questions, fut,
                ),
                name="frontend-ask-question",
                admission=self._admit_interaction,
            )
        except ApplicationStoppingError:
            self._pending_asks.pop(request_id, None)
            self._ask_session_map.pop(request_id, None)
            return {"error": "Application is stopping, cannot send question"}
        finally:
            self._pending_asks.pop(request_id, None)
            self._ask_session_map.pop(request_id, None)
            if not fut.done():
                fut.cancel()

    async def _ask_question(
        self,
        ws: WebSocket,
        session_id: str,
        request_id: str,
        questions: list[dict],
        fut: asyncio.Future,
    ) -> dict:
        # 模型构造/序列化错误传播，不作为网络异常吞掉。
        payload = json.dumps({
            "type": "ask_request",
            "session_id": session_id,
            "request_id": request_id,
            "questions": questions,
        }, ensure_ascii=False)
        if not await self._send_raw(ws, payload, session_id):
            return {"error": "WebSocket disconnected during question request"}
        result_str: str = await fut
        result: dict = json.loads(result_str)
        answers: list[dict] | None = result.get("answers")
        answered_any = bool(answers) and any(
            a.get("selected") or a.get("custom_text") for a in answers
        )
        return {
            "questions": questions,
            "answers": answers,
            "answered": answered_any,
        }

    def resolve_ask(self, request_id: str, answers: list[AskAnswerItem] | None = None) -> bool:
        """解析前端发来的提问结果；answers 为按题回答列表，None 表示整表跳过。"""
        logger.info("Resolve ask | request_id=%s answers=%s", request_id, "skip" if answers is None else f"{len(answers)} items")
        fut = self._pending_asks.pop(request_id, None)
        self._ask_session_map.pop(request_id, None)
        if fut and not fut.done():
            dumped = [a.model_dump(exclude_none=True) if isinstance(a, AskAnswerItem) else a for a in (answers or [])]
            result = json.dumps({"answers": dumped}, ensure_ascii=False)
            fut.set_result(result)
            logger.info("Resolve ask ok | request_id=%s", request_id)
            return True
        logger.warning("Resolve ask fail | request_id=%s (no pending future)", request_id)
        return False

    def _deny_session_asks(self, session_id: str) -> None:
        for rid in list(self._ask_session_map.keys()):
            if self._ask_session_map.get(rid) == session_id:
                self.resolve_ask(rid, answers=None)

    def _deny_all_asks(self) -> None:
        for rid in list(self._pending_asks.keys()):
            fut = self._pending_asks.pop(rid, None)
            self._ask_session_map.pop(rid, None)
            if fut is not None and not fut.done():
                fut.set_result(json.dumps(
                    {"answers": None}, ensure_ascii=False,
                ))

    # -- 事件推送 --

    async def emit_tool_call(self, session_id: str, tool_name: str,
                             tool_call_id: str, args: dict,
                             character_name: str | None = None) -> None:
        visible_args = {k: v for k, v in args.items() if not k.startswith("_")}
        await self._send_msg(session_id, "tool_call", tool_name,
                             json.dumps(visible_args, ensure_ascii=False),
                             tool_call_id=tool_call_id,
                             character_name=character_name)

    async def emit_tool_result(self, session_id: str, tool_name: str,
                               tool_call_id: str, content: str,
                               character_name: str | None = None,
                               tool_call_meta: dict | None = None,
                               embedded_messages: list[dict] | None = None,
                               consumed_client_message_ids: list[str] | None = None) -> None:
        await self._send_msg(session_id, "tool_result", tool_name, content,
                             tool_call_id=tool_call_id,
                             character_name=character_name,
                             tool_call_meta=tool_call_meta,
                             embedded_messages=embedded_messages,
                             consumed_client_message_ids=consumed_client_message_ids)

    async def emit_history_updated(self, session_id: str) -> None:
        event = HistoryUpdatedEvent(session_id=session_id)
        await self._requests.run_request(
            lambda: self._send_message_model(session_id, event),
            name="frontend-history-updated",
            admission=self._admit_send,
            cancel_timeout=SHUTDOWN_SEND_TIMEOUT_SECONDS,
        )

    async def emit_tool_calls_discarded(
        self, session_id: str, stream_id: str, tool_call_ids: list[str],
    ) -> None:
        if not session_id or not stream_id or any(not tool_call_id for tool_call_id in tool_call_ids):
            raise ValueError("Discarded tool calls require session, stream and non-empty call IDs")
        await self._send_msg(
            session_id,
            "tool_calls_discarded",
            "",
            "",
            stream_id=stream_id,
            tool_call_ids=tool_call_ids,
        )

    async def emit_user_message(self, session_id: str, content: MessageContent,
                                character_name: str, message_index: int,
                                visible_characters: list[str] | None = None,
                                response_characters: list[str] | None = None,
                                client_message_id: str | None = None,
                                message_suffix: str | None = None,
                                dynamic_message_suffix: str | None = None) -> None:
        msg = Message(
            type=MessageType.USER_MESSAGE,
            session_id=session_id,
            content=content,
            character_name=character_name,
            index=message_index,
            visible_characters=visible_characters,
            response_characters=response_characters,
            client_message_id=client_message_id,
            message_suffix=message_suffix,
            dynamic_message_suffix=dynamic_message_suffix,
        )
        await self._requests.run_request(
            lambda: self._send_message_model(session_id, msg),
            name="frontend-emit-user-message",
            admission=self._admit_send,
            cancel_timeout=SHUTDOWN_SEND_TIMEOUT_SECONDS,
        )

    async def emit_assistant_message(self, session_id: str, content: MessageContent,
                                     character_name: str,
                                     visible_characters: list[str] | None = None,
                                     response_characters: list[str] | None = None) -> None:
        msg = Message(
            type=MessageType.ASSISTANT_MESSAGE,
            session_id=session_id,
            content=content,
            character_name=character_name,
            visible_characters=visible_characters,
            response_characters=response_characters,
        )
        await self._requests.run_request(
            lambda: self._send_message_model(session_id, msg),
            name="frontend-emit-assistant-message",
            admission=self._admit_send,
            cancel_timeout=SHUTDOWN_SEND_TIMEOUT_SECONDS,
        )

    async def emit_stream_delta(self, session_id: str, stream_id: str,
                                delta: str = "", reasoning_delta: str = "",
                                tool_call: ToolCallRequest | None = None,
                                tool_call_delta: ToolCallDelta | None = None,
                                character_name: str | None = None) -> None:
        event = StreamDeltaEvent(
            session_id=session_id,
            stream_id=stream_id,
            delta=delta or None,
            reasoning_delta=reasoning_delta or None,
            tool_call=tool_call,
            tool_call_delta=tool_call_delta,
            character_name=character_name or None,
        )
        await self._requests.run_request(
            lambda: self._send_stream_event(event),
            name="frontend-emit-stream-delta",
            admission=self._admit_send,
            cancel_timeout=SHUTDOWN_SEND_TIMEOUT_SECONDS,
        )

    async def emit_stream_done(self, session_id: str, stream_id: str,
                               finish_reason: str = "stop",
                               content: str = "",
                               metrics: MessageMetrics | None = None) -> None:
        event = StreamDoneEvent(
            session_id=session_id,
            stream_id=stream_id,
            finish_reason=finish_reason,
            # 维持既有语义：调用方的空文本省略，前端保留累计的部分正文。
            content=content or None,
            metrics=metrics,
        )
        await self._requests.run_request(
            lambda: self._send_stream_event(event),
            name="frontend-emit-stream-done",
            admission=self._admit_send,
            cancel_timeout=SHUTDOWN_SEND_TIMEOUT_SECONDS,
        )

    async def _send_stream_event(self, event: StreamEvent) -> None:
        """流式事件唯一发送边界；模型/序列化错误不作为网络异常吞掉。"""
        ws = self.get_ws(event.session_id)
        if ws is None:
            return
        # 模型构造/序列化错误在此前已发生；此处只捕获网络发送异常。
        payload = event.model_dump_json(exclude_none=True)
        await self._send_raw(ws, payload, event.session_id)

    async def emit_usage_update(self, session_id: str, token_usage: int,
                                context_tokens: int) -> None:
        payload = json.dumps({
            "token_usage": token_usage,
            "context_tokens": context_tokens,
        }, ensure_ascii=False)
        await self._send_msg(session_id, "usage_update", "", payload)

    async def emit_progress(self, session_id: str, tool_name: str,
                            payload: str) -> None:
        await self._send_msg(session_id, "task_progress", tool_name, payload)

    async def emit_clipboard_display(self, session_id: str, tool_name: str,
                                     payload: str) -> None:
        await self._send_msg(session_id, "clipboard_display", tool_name, payload)

    async def emit_subagent_update(self, session_id: str, payload: dict) -> None:
        await self._send_msg(session_id, "subagent_update", "",
                             json.dumps(payload, ensure_ascii=False))

    async def emit_system_message(self, session_id: str, content: str,
                                  history_index: int | None = None,
                                  is_system_status: bool = False) -> None:
        """推送系统消息到前端。"""
        msg = Message(
            type=MessageType.SYSTEM,
            session_id=session_id,
            content=content,
            index=history_index,
            is_system_status=is_system_status or None,
        )
        await self._requests.run_request(
            lambda: self._send_message_model(session_id, msg),
            name="frontend-emit-system-message",
            admission=self._admit_send,
            cancel_timeout=SHUTDOWN_SEND_TIMEOUT_SECONDS,
        )

    async def _send_message_model(self, session_id: str, msg: Message | HistoryUpdatedEvent) -> None:
        """既有非流式 Message 发送边界；模型构造/序列化错误传播。"""
        ws = self.get_ws(session_id)
        if ws is None:
            return
        payload = json.dumps(msg.model_dump(exclude_none=True), ensure_ascii=False)
        await self._send_raw(ws, payload, session_id)

    async def _send_msg(self, session_id: str, event_type: str,
                        tool_name: str, payload: str, *,
                        tool_call_id: str = "",
                        character_name: str | None = None,
                        tool_call_meta: dict | None = None,
                        embedded_messages: list[dict] | None = None,
                        consumed_client_message_ids: list[str] | None = None,
                        stream_id: str = "",
                        tool_call_ids: list[str] | None = None) -> None:
        """推送既有非流式事件；流式事件只走 _send_stream_event。"""
        ws = self.get_ws(session_id)
        if ws is None:
            return

        if event_type == "tool_call":
            msg_type = MessageType.TOOL_CALL
            data = json.loads(payload) if payload else None
            msg = Message(type=msg_type, session_id=session_id, tool=tool_name, args=data,
                          tool_call_id=tool_call_id or None,
                          character_name=character_name)
        elif event_type == "tool_result":
            msg_type = MessageType.TOOL_RESULT
            msg = Message(type=msg_type, session_id=session_id, tool=tool_name,
                          result=payload, tool_call_id=tool_call_id,
                          character_name=character_name,
                          tool_call_meta=tool_call_meta,
                          embedded_messages=embedded_messages,
                          consumed_client_message_ids=consumed_client_message_ids)
        elif event_type == "usage_update":
            msg = Message(type=MessageType.SYSTEM, session_id=session_id, content=payload)
        elif event_type == "task_progress":
            msg = Message(type=MessageType.TASK_PROGRESS, session_id=session_id, tool=tool_name,
                          result=payload)
        elif event_type == "clipboard_display":
            msg = Message(type=MessageType.CLIPBOARD_DISPLAY, session_id=session_id, tool=tool_name,
                          result=payload)
        elif event_type == "subagent_update":
            msg = Message(type=MessageType.SUBAGENT_UPDATE, session_id=session_id,
                          result=payload)
        elif event_type == "tool_calls_discarded":
            msg = Message(
                type=MessageType.TOOL_CALLS_DISCARDED,
                session_id=session_id,
                stream_id=stream_id,
                tool_call_ids=tool_call_ids,
            )
        else:
            return

        await self._requests.run_request(
            lambda: self._send_message_model(session_id, msg),
            name=f"frontend-send-{event_type}",
            admission=self._admit_send,
            cancel_timeout=SHUTDOWN_SEND_TIMEOUT_SECONDS,
        )

    async def virtual_shotdown(self) -> None:
        """所有System业务收尾完成之后，等待实际输出资源关闭。"""
        await self.close_all_connections()


class ParentAgentSink(IAgentSink):
    """子 Agent 的交互抽象 — 通过 outbox + orchestrator 与父 Agent 通信。

    子 Agent 不能直接与前端通信；所有交互事件通过 outbox
    和 orchestrator 转发到父 Agent，最终由 FrontendSink 处理。
    """

    def __init__(self, loop: SubAgentLoop) -> None:  # loop: SubAgentLoop
        self._loop = loop

    async def ask_question(self, questions: list[dict], session_id: str = "") -> dict:
        """子 Agent 不支持直接提问。"""
        return {"error": "SubAgent does not support Ask — use parent agent tools instead"}

    async def request_approval(self, tool_name: str, args: dict,
                               reason: str = "", content: str = "",
                               session_id: str = "") -> ApprovalResult:
        """将审批请求放入子 Agent 的待审批队列，阻塞等待父 Agent 决策。

        脱手模式走 request_user_confirm 到父 session（由 approval 模型审批）；
        正常模式创建 PendingToolCall 入 _pending_approvals 队列，
        orchestrator 的 _collect_and_inject 会收集待审批项目注入父 Agent，
        父 Agent 通过 approve_subagent 工具回调 approve_tools() 驱动 Future。
        """
        import uuid
        from entity.puretype import ApprovalResult, ToolCallRequest
        from component.approval import is_handsfree_mode, request_user_confirm
        from subagent.loop import PendingToolCall

        # 脱手模式：直接向父 session 发起审批（走 approval 模型）
        if is_handsfree_mode(self._loop.parent_session_id):
            result = await request_user_confirm(
                session_id=self._loop.parent_session_id,
                tool_name=tool_name,
                args=args,
                reason=reason or "Sub-agent initiated tool call",
                content=content or f"Sub-agent {tool_name} tool call",
            )
            return result

        # 正常模式：创建 PendingToolCall 入队列，等待父 Agent 审批
        tool_call_id = uuid.uuid4().hex[:8]
        tc = ToolCallRequest(id=tool_call_id, name=tool_name, arguments=args)
        pending = PendingToolCall(tc)
        self._loop.add_pending_approval(pending)

        self._loop.emit_event(
            "approval_pending",
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_args=args,
        )

        try:
            result = await pending.result
            if result["approved"]:
                self._loop.emit_event(
                    "approval_decision",
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    content="approved",
                )
                return ApprovalResult(action="allow_once", denied_by="")
            else:
                reason_text = result.get("reason", "Rejected by parent agent.")
                self._loop.emit_event(
                    "approval_decision",
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    content=f"rejected: {reason_text}",
                )
                return ApprovalResult(action="deny", deny_reason=reason_text, denied_by="parent_agent")
        except RuntimeError as exc:
            self._loop.emit_event(
                "approval_decision",
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                content=f"rejected: {exc}",
            )
            return ApprovalResult(action="deny", deny_reason=str(exc), denied_by="parent_agent")

    async def emit_tool_call(self, session_id: str, tool_name: str,
                             tool_call_id: str, args: dict,
                             character_name: str | None = None) -> None:
        self._loop.emit_event("tool_call", tool_call_id=tool_call_id,
                         tool_name=tool_name, tool_args=args)

    async def emit_tool_result(self, session_id: str, tool_name: str,
                               tool_call_id: str, content: str,
                               character_name: str | None = None,
                               tool_call_meta: dict | None = None,
                               embedded_messages: list[dict] | None = None,
                               consumed_client_message_ids: list[str] | None = None) -> None:
        # consumed_client_message_ids 仅为接口一致性；子 Agent 工具结果不消费主会话消息队列
        self._loop.emit_event("tool_result", tool_call_id=tool_call_id,
                         tool_name=tool_name, content=content)

    async def emit_history_updated(self, session_id: str) -> None:
        # 子会话没有父主会话 History 的更新权限。
        return

    async def emit_tool_calls_discarded(
        self, session_id: str, stream_id: str, tool_call_ids: list[str],
    ) -> None:
        # SubAgent tools do not own an independent frontend stream.
        return

    async def emit_user_message(self, session_id: str, content: MessageContent,
                                character_name: str, message_index: int,
                                visible_characters: list[str] | None = None,
                                response_characters: list[str] | None = None,
                                client_message_id: str | None = None,
                                message_suffix: str | None = None,
                                dynamic_message_suffix: str | None = None) -> None:
        # 子 Agent 的用户消息不直接显示在父会话主聊天区，由 subagent_update 处理
        pass

    async def emit_assistant_message(self, session_id: str, content: MessageContent,
                                     character_name: str,
                                     visible_characters: list[str] | None = None,
                                     response_characters: list[str] | None = None) -> None:
        # 子 Agent 的 assistant 消息不直接显示在父会话主聊天区，由 subagent_update 处理
        pass

    async def emit_stream_delta(self, session_id: str, stream_id: str,
                                delta: str = "", reasoning_delta: str = "",
                                tool_call: ToolCallRequest | None = None,
                                tool_call_delta: ToolCallDelta | None = None,
                                character_name: str | None = None) -> None:
        if delta:
            self._loop.emit_event("assistant", content=delta, reasoning=reasoning_delta,
                             character_name=character_name)
        if tool_call_delta:
            # 子会话事件仍走独立的反馈通道，按属性适配而非降级/展开模型。
            self._loop.emit_event(
                "tool_call_delta",
                id=tool_call_delta.id,
                index=tool_call_delta.index,
                name=tool_call_delta.name,
                args_delta=tool_call_delta.args_delta,
                phase=tool_call_delta.phase.value,
            )

    async def emit_stream_done(self, session_id: str, stream_id: str,
                               finish_reason: str = "stop",
                               content: str = "",
                               metrics: MessageMetrics | None = None) -> None:
        """转发流结束事件到父 Agent 前端。"""
        try:
            from system.application import Application
            sink = Application.current().get_system(IFrontendSink)
            await sink.emit_stream_done(
                self._loop.parent_session_id, stream_id, finish_reason,
                content=content,
                metrics=metrics,
            )
        except Exception:
            logger.warning(
                "Failed to forward stream_done to parent session=%s", session_id, exc_info=True
            )

    async def emit_usage_update(self, session_id: str, token_usage: int,
                                context_tokens: int) -> None:
        """转发 token 消耗更新到父 Agent 前端。"""
        try:
            from system.application import Application
            sink = Application.current().get_system(IFrontendSink)
            await sink.emit_usage_update(
                self._loop.parent_session_id, token_usage, context_tokens,
            )
        except Exception:
            logger.warning(
                "Failed to forward usage_update to parent session=%s", session_id, exc_info=True
            )

    async def emit_progress(self, session_id: str, tool_name: str,
                            payload: str) -> None:
        """转发进度事件到父 Agent 前端。"""
        try:
            from system.application import Application
            sink = Application.current().get_system(IFrontendSink)
            await sink.emit_progress(
                self._loop.parent_session_id, tool_name, payload,
            )
        except Exception:
            logger.warning(
                "Failed to forward progress event to parent session=%s", session_id, exc_info=True
            )

    async def emit_clipboard_display(self, session_id: str, tool_name: str,
                                     payload: str) -> None:
        """转发剪贴板展示事件到父 Agent 前端。"""
        try:
            from system.application import Application
            sink = Application.current().get_system(IFrontendSink)
            await sink.emit_clipboard_display(
                self._loop.parent_session_id, tool_name, payload,
            )
        except Exception:
            logger.warning(
                "Failed to forward clipboard_display to parent session=%s", session_id, exc_info=True
            )

    async def emit_subagent_update(self, session_id: str, payload: dict) -> None:
        """转发子 Agent 状态更新到父 Agent 前端。"""
        try:
            from system.application import Application
            sink = Application.current().get_system(IFrontendSink)
            await sink.emit_subagent_update(
                self._loop.parent_session_id, payload,
            )
        except Exception:
            logger.warning(
                "Failed to forward subagent_update to parent session=%s", session_id, exc_info=True
            )

    async def emit_system_message(self, session_id: str, content: str,
                                  history_index: int | None = None,
                                  is_system_status: bool = False) -> None:
        """转发系统消息到父 Agent 前端。"""
        try:
            from system.application import Application
            sink = Application.current().get_system(IFrontendSink)
            await sink.emit_system_message(
                self._loop.parent_session_id,
                content,
                history_index=history_index,
                is_system_status=is_system_status,
            )
        except Exception:
            logger.warning(
                "Failed to forward system message to parent session=%s", session_id, exc_info=True,
            )