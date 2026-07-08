"""Agent 交互抽象 — AgentSink 定义向上（用户/父Agent）通信的统一接口。

- FrontendSink：主 Agent 通过 WebSocket 与前端用户交互
- ParentAgentSink：子 Agent 通过 outbox + orchestrator 与父 Agent 交互
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from abc import ABC, abstractmethod
from typing import * # type: ignore

if TYPE_CHECKING:
    from fastapi import WebSocket
    from component.approval import ApprovalResult
    from subagent.loop import SubAgentLoop

logger = logging.getLogger(__name__)


class AgentSink(ABC):
    """Agent 向上层（用户/父Agent）通信的抽象接口。

    主 Agent 使用 FrontendSink，子 Agent 使用 ParentAgentSink。
    """

    @abstractmethod
    async def ask_question(self, question: str, options: list[dict] | None = None,
                           allow_custom: bool = True, session_id: str = "") -> dict:
        """向用户提问，等待回答后返回结果。"""
        ...

    @abstractmethod
    async def request_approval(self, tool_name: str, args: dict,
                               reason: str = "", content: str = "",
                               session_id: str = "") -> "ApprovalResult":
        """请求审批一个工具调用。"""
        ...

    @abstractmethod
    async def emit_tool_call(self, session_id: str, tool_name: str,
                             tool_call_id: str, args: dict,
                             character_name: str | None = None) -> None:
        """推送 tool_call 事件。"""
        ...

    @abstractmethod
    async def emit_tool_result(self, session_id: str, tool_name: str,
                               tool_call_id: str, content: str,
                               character_name: str | None = None) -> None:
        """推送 tool_result 事件。"""
        ...

    @abstractmethod
    async def emit_user_message(self, session_id: str, content: Any,
                                character_name: str, message_index: int,
                                visible_characters: list[str] | None = None,
                                response_characters: list[str] | None = None,
                                client_message_id: str | None = None,
                                message_suffix: str | None = None,
                                dynamic_message_suffix: str | None = None) -> None:
        """推送用户消息到前端。"""
        ...

    @abstractmethod
    async def emit_assistant_message(self, session_id: str, content: Any,
                                     character_name: str,
                                     visible_characters: list[str] | None = None,
                                     response_characters: list[str] | None = None) -> None:
        """推送 assistant 消息到前端。"""
        ...

    @abstractmethod
    async def emit_stream_delta(self, session_id: str, stream_id: str,
                                delta: str = "", reasoning_delta: str = "",
                                tool_call: dict | None = None,
                                character_name: str | None = None) -> None:
        """推送流式增量。"""
        ...

    @abstractmethod
    async def emit_stream_done(self, session_id: str, stream_id: str,
                               finish_reason: str = "stop") -> None:
        """推送流结束事件。"""
        ...

    @abstractmethod
    async def emit_usage_update(self, session_id: str, token_usage: int,
                                context_tokens: int) -> None:
        """推送 token 消耗更新。"""
        ...

    @abstractmethod
    async def emit_progress(self, session_id: str, tool_name: str,
                            payload: str) -> None:
        """推送进度事件。"""
        ...

    @abstractmethod
    async def emit_clipboard_display(self, session_id: str, tool_name: str,
                                     payload: str) -> None:
        """推送剪贴板展示事件。"""
        ...

    @abstractmethod
    async def emit_subagent_update(self, session_id: str, payload: dict) -> None:
        """推送子 Agent 状态更新。"""
        ...

    @abstractmethod
    async def emit_system_message(self, session_id: str, content: str) -> None:
        """推送系统消息到前端。

        Args:
            session_id: 目标会话 ID。
            content: 系统消息文本内容。
        """
        ...


class FrontendSink(AgentSink):
    """主 Agent 的交互抽象 — 通过 WebSocket 与前端用户通信。

    持有 _pending_confirms 和 _pending_asks Future 映射，
    等待前端通过 HTTP 或 WebSocket 返回结果。
    """

    def __init__(self) -> None:
        # session_id → WebSocket
        self._ws_sinks: dict[str, WebSocket] = {}
        # {request_id: Future[ApprovalResult]}
        self._pending_confirms: dict[str, asyncio.Future] = {}
        # {request_id: session_id}
        self._confirm_session_map: dict[str, str] = {}
        # {request_id: Future[str]}
        self._pending_asks: dict[str, asyncio.Future] = {}
        # {request_id: session_id}
        self._ask_session_map: dict[str, str] = {}

    # -- WebSocket 管理 --

    def register_ws(self, session_id: str, ws: WebSocket) -> None:
        self._ws_sinks[session_id] = ws

    def unregister_ws(self, session_id: str) -> None:
        self._ws_sinks.pop(session_id, None)
        # 自动拒绝该 session 的所有待处理确认和提问
        self._deny_session_confirms(session_id)
        self._deny_session_asks(session_id)

    def get_ws(self, session_id: str) -> WebSocket | None:
        return self._ws_sinks.get(session_id)

    # -- 审批请求 --

    async def request_approval(self, tool_name: str, args: dict,
                               reason: str = "", content: str = "",
                               session_id: str = "") -> "ApprovalResult":
        """向 WebSocket 发送 confirm_request 并等待前端响应。"""
        from component.approval import ApprovalResult

        request_id: str = uuid.uuid4().hex[:8]
        loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
        fut: asyncio.Future[ApprovalResult] = loop.create_future()
        self._pending_confirms[request_id] = fut
        self._confirm_session_map[request_id] = session_id

        ws = self._ws_sinks.get(session_id)
        if ws is None:
            self._pending_confirms.pop(request_id, None)
            self._confirm_session_map.pop(request_id, None)
            return ApprovalResult(action="deny", deny_reason="WebSocket not connected", denied_by="system")

        try:
            from gateway.chat import Message, MessageType
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
            )
            await ws.send_text(msg.to_json())
        except Exception as exc:
            self._pending_confirms.pop(request_id, None)
            self._confirm_session_map.pop(request_id, None)
            logger.exception("Failed to send confirm_request to session=%s: %s", session_id, exc)
            return ApprovalResult(action="deny", deny_reason=f"Failed to push to frontend: {exc}", denied_by="system")

        try:
            return await fut
        except asyncio.CancelledError:
            self._pending_confirms.pop(request_id, None)
            self._confirm_session_map.pop(request_id, None)
            return ApprovalResult(action="deny", deny_reason="Cancelled", denied_by="system")

    def resolve_confirm(self, request_id: str, action: str,
                        deny_reason: str | None = None,
                        denied_by: str = "user") -> bool:
        """解析前端发来的审批结果。"""
        from component.approval import ApprovalResult
        fut = self._pending_confirms.pop(request_id, None)
        self._confirm_session_map.pop(request_id, None)
        if fut and not fut.done():
            fut.set_result(ApprovalResult(action=action, deny_reason=deny_reason, denied_by=denied_by))
            return True
        return False

    def _deny_session_confirms(self, session_id: str) -> None:
        from component.approval import ApprovalResult
        for rid in list(self._confirm_session_map.keys()):
            if self._confirm_session_map.get(rid) == session_id:
                self.resolve_confirm(rid, "deny", deny_reason="WebSocket disconnected", denied_by="system")

    # -- 提问请求 --

    async def ask_question(self, question: str, options: list[dict] | None = None,
                           allow_custom: bool = True, session_id: str = "") -> dict:
        """向 WebSocket 发送 ask_request 并等待前端响应。"""
        request_id: str = uuid.uuid4().hex[:8]
        loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self._pending_asks[request_id] = fut
        self._ask_session_map[request_id] = session_id

        ws = self._ws_sinks.get(session_id)
        if ws is None:
            self._pending_asks.pop(request_id, None)
            self._ask_session_map.pop(request_id, None)
            return {"error": "WebSocket connection unavailable, cannot send question"}

        try:
            await ws.send_text(json.dumps({
                "type": "ask_request",
                "session_id": session_id,
                "request_id": request_id,
                "question": question,
                "options": options or [],
                "allow_custom": allow_custom,
            }, ensure_ascii=False))
        except Exception as exc:
            self._pending_asks.pop(request_id, None)
            self._ask_session_map.pop(request_id, None)
            logger.exception("Failed to send ask_request to session=%s: %s", session_id, exc)
            return {"error": f"Failed to push question via WebSocket: {exc}"}

        try:
            result_str: str = await fut
            result: dict = json.loads(result_str)
            return {
                "question": question,
                "option": result.get("option"),
                "custom_text": result.get("custom_text"),
                "answered": result.get("option") is not None or result.get("custom_text") is not None,
            }
        except asyncio.CancelledError:
            self._pending_asks.pop(request_id, None)
            self._ask_session_map.pop(request_id, None)
            return {"error": "Question request was cancelled"}
        except Exception as exc:
            self._pending_asks.pop(request_id, None)
            self._ask_session_map.pop(request_id, None)
            logger.exception("Failed to handle ask response for session=%s: %s", session_id, exc)
            return {"error": f"Question handling error: {exc}"}

    def resolve_ask(self, request_id: str, option: str | None = None,
                    custom_text: str | None = None) -> bool:
        """解析前端发来的提问结果。"""
        fut = self._pending_asks.pop(request_id, None)
        self._ask_session_map.pop(request_id, None)
        if fut and not fut.done():
            result = json.dumps({"option": option, "custom_text": custom_text}, ensure_ascii=False)
            fut.set_result(result)
            return True
        return False

    def _deny_session_asks(self, session_id: str) -> None:
        for rid in list(self._ask_session_map.keys()):
            if self._ask_session_map.get(rid) == session_id:
                self.resolve_ask(rid, option=None, custom_text=None)

    # -- 事件推送 --

    async def emit_tool_call(self, session_id: str, tool_name: str,
                             tool_call_id: str, args: dict,
                             character_name: str | None = None) -> None:
        await self._send_msg(session_id, "tool_call", tool_name,
                             json.dumps(args, ensure_ascii=False),
                             character_name=character_name)

    async def emit_tool_result(self, session_id: str, tool_name: str,
                               tool_call_id: str, content: str,
                               character_name: str | None = None) -> None:
        await self._send_msg(session_id, "tool_result", tool_name, content,
                             tool_call_id=tool_call_id,
                             character_name=character_name)

    async def emit_user_message(self, session_id: str, content: Any,
                                character_name: str, message_index: int,
                                visible_characters: list[str] | None = None,
                                response_characters: list[str] | None = None,
                                client_message_id: str | None = None,
                                message_suffix: str | None = None,
                                dynamic_message_suffix: str | None = None) -> None:
        from gateway.chat import Message, MessageType
        ws = self._ws_sinks.get(session_id)
        if ws is None:
            return
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
        try:
            await ws.send_text(msg.to_json())
        except Exception:
            logger.warning("Failed to send user_message to session=%s", session_id, exc_info=True)

    async def emit_assistant_message(self, session_id: str, content: Any,
                                     character_name: str,
                                     visible_characters: list[str] | None = None,
                                     response_characters: list[str] | None = None) -> None:
        from gateway.chat import Message, MessageType
        ws = self._ws_sinks.get(session_id)
        if ws is None:
            return
        msg = Message(
            type=MessageType.ASSISTANT_MESSAGE,
            session_id=session_id,
            content=content,
            character_name=character_name,
            visible_characters=visible_characters,
            response_characters=response_characters,
        )
        try:
            await ws.send_text(msg.to_json())
        except Exception:
            logger.warning("Failed to send assistant_message to session=%s", session_id, exc_info=True)

    async def emit_stream_delta(self, session_id: str, stream_id: str,
                                delta: str = "", reasoning_delta: str = "",
                                tool_call: dict | None = None,
                                character_name: str | None = None) -> None:
        data: dict = {"stream_id": stream_id}
        if delta:
            data["delta"] = delta
        if reasoning_delta:
            data["reasoning_delta"] = reasoning_delta
        if tool_call:
            data["tool_call"] = tool_call
        if character_name:
            data["character_name"] = character_name
        await self._send_msg(session_id, "stream_delta", "",
                             json.dumps(data, ensure_ascii=False))

    async def emit_stream_done(self, session_id: str, stream_id: str,
                               finish_reason: str = "stop") -> None:
        await self._send_msg(session_id, "stream_done", "",
                             json.dumps({"stream_id": stream_id, "finish_reason": finish_reason},
                                        ensure_ascii=False))

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

    async def emit_system_message(self, session_id: str, content: str) -> None:
        """推送系统消息到前端。"""
        try:
            ws = self._ws_sinks.get(session_id)
            if ws is None:
                return
            from gateway.chat import Message, MessageType
            msg = Message(
                type=MessageType.SYSTEM,
                session_id=session_id,
                content=content,
            )
            await ws.send_text(msg.to_json())
        except Exception:
            logger.warning(
                "Failed to send system message | session=%s", session_id, exc_info=True,
            )

    async def _send_msg(self, session_id: str, event_type: str,
                        tool_name: str, payload: str, *,
                        tool_call_id: str = "",
                        character_name: str | None = None) -> None:
        """通过 WebSocket 推送一条事件消息。"""
        ws = self._ws_sinks.get(session_id)
        if ws is None:
            return
        from gateway.chat import Message, MessageType

        if event_type == "tool_call":
            msg_type = MessageType.TOOL_CALL
            data = json.loads(payload) if payload else None
            msg = Message(type=msg_type, session_id=session_id, tool=tool_name, args=data,
                          character_name=character_name)
        elif event_type == "tool_result":
            msg_type = MessageType.TOOL_RESULT
            msg = Message(type=msg_type, session_id=session_id, tool=tool_name,
                          result=payload, tool_call_id=tool_call_id,
                          character_name=character_name)
        elif event_type == "stream_delta":
            data = json.loads(payload)
            msg = Message(
                type=MessageType.STREAM_DELTA, session_id=session_id,
                stream_id=data.get("stream_id"),
                delta=data.get("delta"),
                reasoning_delta=data.get("reasoning_delta"),
                content=json.dumps({"tool_call": data["tool_call"]}) if data.get("tool_call") else None,
                character_name=data.get("character_name"),
            )
        elif event_type == "stream_done":
            data = json.loads(payload)
            msg = Message(
                type=MessageType.STREAM_DONE, session_id=session_id,
                stream_id=data.get("stream_id"),
                finish_reason=data.get("finish_reason"),
            )
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
        else:
            return

        try:
            await ws.send_text(msg.to_json())
        except Exception:
            logger.warning(
                "Failed to send %s event to session=%s", event_type, session_id, exc_info=True
            )


class ParentAgentSink(AgentSink):
    """子 Agent 的交互抽象 — 通过 outbox + orchestrator 与父 Agent 通信。

    子 Agent 不能直接与前端通信；所有交互事件通过 outbox
    和 orchestrator 转发到父 Agent，最终由 FrontendSink 处理。
    """

    def __init__(self, loop: SubAgentLoop) -> None:  # loop: SubAgentLoop
        self._loop = loop

    async def ask_question(self, question: str, options: list[dict] | None = None,
                           allow_custom: bool = True, session_id: str = "") -> dict:
        """子 Agent 不支持直接提问。"""
        return {"error": "SubAgent does not support ask_question — use parent agent tools instead"}

    async def request_approval(self, tool_name: str, args: dict,
                               reason: str = "", content: str = "",
                               session_id: str = "") -> "ApprovalResult":
        """将审批请求放入子 Agent 的待审批队列，阻塞等待父 Agent 决策。

        脱手模式走 request_user_confirm 到父 session（由 approval 模型审批）；
        正常模式创建 PendingToolCall 入 _pending_approvals 队列，
        orchestrator 的 _collect_and_inject 会收集待审批项目注入父 Agent，
        父 Agent 通过 approve_subagent 工具回调 approve_tools() 驱动 Future。
        """
        import uuid
        from component.approval import ApprovalResult, is_handsfree_mode, request_user_confirm
        from component.llm import ToolCall
        from subagent.loop import PendingToolCall

        # 脱手模式：直接向父 session 发起审批（走 approval 模型）
        if is_handsfree_mode(self._loop._parent_session_id):
            result = await request_user_confirm(
                session_id=self._loop._parent_session_id,
                tool_name=tool_name,
                args=args,
                reason=reason or "Sub-agent initiated tool call",
                content=content or f"Sub-agent {tool_name} tool call",
                ask_agent_callback=None,
            )
            return result

        # 正常模式：创建 PendingToolCall 入队列，等待父 Agent 审批
        tool_call_id = uuid.uuid4().hex[:8]
        tc = ToolCall(id=tool_call_id, name=tool_name, arguments=args)
        pending = PendingToolCall(tc)
        self._loop._pending_approvals.append(pending)
        self._loop._paused_event.clear()

        self._loop._emit(
            "approval_pending",
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_args=args,
        )

        try:
            result = await pending.result
            if result["approved"]:
                self._loop._emit(
                    "approval_decision",
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    content="approved",
                )
                return ApprovalResult(action="allow_once", denied_by="")
            else:
                reason_text = result.get("reason", "Rejected by parent agent.")
                self._loop._emit(
                    "approval_decision",
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    content=f"rejected: {reason_text}",
                )
                return ApprovalResult(action="deny", deny_reason=reason_text, denied_by="parent_agent")
        except RuntimeError as exc:
            self._loop._emit(
                "approval_decision",
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                content=f"rejected: {exc}",
            )
            return ApprovalResult(action="deny", deny_reason=str(exc), denied_by="parent_agent")

    async def emit_tool_call(self, session_id: str, tool_name: str,
                             tool_call_id: str, args: dict,
                             character_name: str | None = None) -> None:
        self._loop._emit("tool_call", tool_call_id=tool_call_id,
                         tool_name=tool_name, tool_args=args)

    async def emit_tool_result(self, session_id: str, tool_name: str,
                               tool_call_id: str, content: str,
                               character_name: str | None = None) -> None:
        self._loop._emit("tool_result", tool_call_id=tool_call_id,
                         tool_name=tool_name, content=content)

    async def emit_user_message(self, session_id: str, content: Any,
                                character_name: str, message_index: int,
                                visible_characters: list[str] | None = None,
                                response_characters: list[str] | None = None,
                                client_message_id: str | None = None,
                                message_suffix: str | None = None,
                                dynamic_message_suffix: str | None = None) -> None:
        # 子 Agent 的用户消息不直接显示在父会话主聊天区，由 subagent_update 处理
        pass

    async def emit_assistant_message(self, session_id: str, content: Any,
                                     character_name: str,
                                     visible_characters: list[str] | None = None,
                                     response_characters: list[str] | None = None) -> None:
        # 子 Agent 的 assistant 消息不直接显示在父会话主聊天区，由 subagent_update 处理
        pass

    async def emit_stream_delta(self, session_id: str, stream_id: str,
                                delta: str = "", reasoning_delta: str = "",
                                tool_call: dict | None = None,
                                character_name: str | None = None) -> None:
        if delta:
            self._loop._emit("assistant", content=delta, reasoning=reasoning_delta,
                             character_name=character_name)

    async def emit_stream_done(self, session_id: str, stream_id: str,
                               finish_reason: str = "stop") -> None:
        """转发流结束事件到父 Agent 前端。"""
        try:
            from system.application import Application
            sink = Application.current().frontend_sink
            if sink is not None:
                await sink.emit_stream_done(
                    self._loop._parent_session_id, stream_id, finish_reason,
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
            sink = Application.current().frontend_sink
            if sink is not None:
                await sink.emit_usage_update(
                    self._loop._parent_session_id, token_usage, context_tokens,
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
            sink = Application.current().frontend_sink
            if sink is not None:
                await sink.emit_progress(
                    self._loop._parent_session_id, tool_name, payload,
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
            sink = Application.current().frontend_sink
            if sink is not None:
                await sink.emit_clipboard_display(
                    self._loop._parent_session_id, tool_name, payload,
                )
        except Exception:
            logger.warning(
                "Failed to forward clipboard_display to parent session=%s", session_id, exc_info=True
            )

    async def emit_subagent_update(self, session_id: str, payload: dict) -> None:
        """转发子 Agent 状态更新到父 Agent 前端。"""
        try:
            from system.application import Application
            sink = Application.current().frontend_sink
            if sink is not None:
                await sink.emit_subagent_update(
                    self._loop._parent_session_id, payload,
                )
        except Exception:
            logger.warning(
                "Failed to forward subagent_update to parent session=%s", session_id, exc_info=True
            )

    async def emit_system_message(self, session_id: str, content: str) -> None:
        """转发系统消息到父 Agent 前端。"""
        try:
            from system.application import Application
            sink = Application.current().frontend_sink
            if sink is not None:
                await sink.emit_system_message(
                    self._loop._parent_session_id, content,
                )
        except Exception:
            logger.warning(
                "Failed to forward system message to parent session=%s", session_id, exc_info=True,
            )