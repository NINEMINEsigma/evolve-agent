"""消息路由：将 WebSocket 消息按类型分发到对应的处理方法。

从 gateway/server.py 的 ws_chat 拆分而来，负责所有消息类型的处理逻辑。
ws_chat 仅保留 WebSocket 连接生命周期管理，通过 ``MessageRouter.route()``
委托消息处理。

USER_MESSAGE 在 route 内同步完成目标校验与输入登记（S21/RV5/RV9）：
主会话登记 ``QueuedMessage``，子会话经编排器同步接收接口登记 Inbox
记录，全部成功后才启动仅处理已登记输入的后台准备任务；关闭刷新按
记录只落 History，不再生成。

消息类型与处理方法映射：
    USER_MESSAGE      → 同步登记 + 后台准备任务
    CONFIRM_RESPONSE  → handle_confirm_response
    ASK_RESPONSE      → handle_ask_response
    INTERRUPT         → handle_interrupt
    FILE_UPLOAD       → handle_file_upload
    HANDSFREE_MODE    → handle_handsfree_mode
    PING              → handle_ping
    CLIENT_DIAGNOSTIC → handle_client_diagnostic
    SYSTEM            → handle_system_message
    其他              → handle_unsupported
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import *

from fastapi import WebSocket

from .chat import Message, MessageType
from entity.constant import (
    SYSTEM_CHARACTER_NAME,
    UPLOAD_FILENAME_TIME_FORMAT,
    UPLOADS_DIR_NAME,
    UPLOADS_WS_PREFIX,
    USER_CHARACTER_NAME,
)
from entity.puretype import (
    ClientInfo,
    QueuedMessage,
    SessionInfo,
    SessionStatus,
)
from entry.agent_support.multimodal import summarize_message_for_log
from system.lifecycle import ApplicationStoppingError
from system.llm_profile_store import ProfileNotFoundError

if TYPE_CHECKING:
    from entry.parent_agent_loop import ParentAgentLoop
    from entry.multi_agent_loop import MultiAgentLoop
    from entry.base_agent_loop import IMainSessionLoop
    from gateway.session_manager import SessionManager
    from subagent.orchestrator import SubAgentOrchestrator

from gateway.session_manager import SessionManager

logger = logging.getLogger(__name__)


def _observe_background_interrupt(task: asyncio.Task) -> None:
    """观察 WS 兼容中断 task，避免后台异常无人获取。"""
    if task.cancelled():
        return
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    if exc is not None:
        logger.error(
            "Background WebSocket interrupt failed | task=%s",
            task.get_name(),
            exc_info=(type(exc), exc, exc.__traceback__),
        )


# ---------------------------------------------------------------------------
# 模块级辅助函数 — 从 server.py 复制，避免循环导入
# ---------------------------------------------------------------------------


def _get_sm() -> SessionManager | None:
    """返回 Application 的 SessionManager。"""
    from system.application import Application
    return Application.current().get_system(SessionManager)


def _get_loop(session_id: str) -> IMainSessionLoop | None:
    """返回指定 session 的 BaseAgentLoop（实际为 ParentAgentLoop 或 MultiAgentLoop）。"""
    sm = _get_sm()
    return sm.get_loop(session_id) if sm else None


def _get_ws(session_id: str) -> WebSocket | None:
    """返回指定 session 的 WebSocket sink。"""
    from system.application import Application
    from entry.agent_sink import FrontendSink
    sink = Application.current().get_system(FrontendSink)
    return sink.get_ws(session_id)


def _extract_text(content: Any) -> str:
    """从消息 content 中提取纯文本（处理 string 和 list 两种格式）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "\n".join(parts)
    return str(content or "")


def get_subagent_orchestrator() -> SubAgentOrchestrator | None:
    """返回 SubAgentOrchestrator 单例。"""
    from system.application import Application
    from subagent.orchestrator import SubAgentOrchestrator
    return Application.current().get_system(SubAgentOrchestrator)


# ---------------------------------------------------------------------------
# MessageRouter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _AcceptedUserMessage:
    """route 内同步接收的非持久化结果；sequence 为主会话已登记记录。"""

    sequence: int | None
    archived: bool = False
    content: Any = ""
    target_sessions: tuple[str, ...] = ()


class MessageRouter:
    """消息路由：将 WebSocket 消息按类型分发到对应的处理方法。

    ``ws_chat`` 在连接建立后创建本实例，消息循环中调用 ``route()`` 分发。
    实例持有 WebSocket 引用和当前 session_id（session 旋转时会更新）。
    """

    def __init__(self, ws: WebSocket, sid: str, conn_token: str = ""):
        self.ws = ws
        self.sid = sid
        self.conn_token = conn_token

    # -- 主分发入口 --------------------------------------------------------

    async def route(self, msg: Message) -> bool:
        """按消息类型分发到对应的处理方法。

        返回 False 表示消息循环应终止（如 agent loop 未就绪时）。"""
        msg.session_id = self.sid  # 信任 server 而非 client

        if msg.type == MessageType.USER_MESSAGE:
            # 同步接收登记；非法目标在产生任何记录之前明确拒绝。
            try:
                accepted, reject_reason = self._accept_user_message(msg)
            except ApplicationStoppingError:
                await self.ws.send_text(
                    json.dumps(
                        Message(
                            type=MessageType.ERROR,
                            session_id=self.sid,
                            message="Application is shutting down; the message was not accepted.",
                        ).model_dump(exclude_none=True),
                        ensure_ascii=False,
                    )
                )
                return True
            if accepted is None:
                if reject_reason is not None:
                    await self._send_router_error(reject_reason)
                return True
            from system.application import Application
            from gateway.system import GatewaySystem
            Application.current().get_system(GatewaySystem).spawn_work(
                self._prepare_user_message(msg, accepted),
                name=f"user-msg-prepare-{self.sid[:8]}",
            )

        elif msg.type == MessageType.CONFIRM_RESPONSE:
            await self.handle_confirm_response(msg)

        elif msg.type == MessageType.ASK_RESPONSE:
            await self.handle_ask_response(msg)

        elif msg.type == MessageType.INTERRUPT:
            await self.handle_interrupt()

        elif msg.type == MessageType.DISGUST:
            await self.handle_disgust()

        elif msg.type == MessageType.FILE_UPLOAD:
            await self.handle_file_upload(msg)

        elif msg.type == MessageType.HANDSFREE_MODE:
            await self.handle_handsfree_mode(msg)

        elif msg.type == MessageType.PING:
            await self.handle_ping()

        elif msg.type == MessageType.CLIENT_DIAGNOSTIC:
            await self.handle_client_diagnostic(msg)

        elif msg.type == MessageType.SYSTEM:
            await self.handle_system_message(msg)

        else:
            await self.handle_unsupported(msg)

        return True

    # -- 消息处理方法 ------------------------------------------------------

    async def _send_router_error(self, message: str) -> None:
        await self.ws.send_text(
            json.dumps(
                Message(
                    type=MessageType.ERROR,
                    session_id=self.sid,
                    message=message,
                ).model_dump(exclude_none=True),
                ensure_ascii=False,
            )
        )

    def _accept_user_message(self, msg: Message) -> "tuple[_AcceptedUserMessage | None, str | None]":
        """同步完成目标/字段/Profile 检查并登记全部输入记录。

        返回 ``(None, reason)`` 表示同步可判定的用户错误且未登记任何记录；
        抛出的 ``ApplicationStoppingError`` 由调用方转换为关闭中拒绝。
        本方法不 await、不做模型或文件 I/O。
        """
        from datetime import datetime
        from system.application import Application
        from system.llm_profile_store import LLMProfileStore

        sm = _get_sm()
        session_info = sm.get(self.sid) if sm is not None else None
        if session_info is None:
            logger.error("User message for unknown session=%s", self.sid)
            raise ApplicationStoppingError(f"Session does not exist: {self.sid}")
        if session_info.status == SessionStatus.archived:
            # 归档目标由后台准备任务按原协议回送错误，不产生输入记录。
            return _AcceptedUserMessage(sequence=None, archived=True), None

        loop = _get_loop(self.sid)
        if loop is None:
            logger.error("Main session loop not configured | session=%s", self.sid)
            raise ApplicationStoppingError(f"Main session loop not ready: {self.sid}")
        if (
            "llm_profile_name" not in msg.model_fields_set
            or not isinstance(msg.llm_profile_name, str)
        ):
            return None, "llm_profile_name must be provided as a string"

        target_sessions: list[str] = msg.target_sessions or ["main"]
        content = msg.content or ""

        # 指定 Profile 必须命中；未命中不产生任何记录。
        if msg.llm_profile_name:
            store = Application.current().get_system(LLMProfileStore)
            try:
                store.get_profile(msg.llm_profile_name)
            except ProfileNotFoundError:
                return None, f"LLM Profile 不存在：{msg.llm_profile_name}"

        main_sequence: int | None = None
        if "main" in target_sessions:
            item = QueuedMessage(
                content=content,
                character_name=USER_CHARACTER_NAME,
                source="ws",
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                client_message_id=msg.client_message_id,
                visible_characters=msg.visible_characters,
                response_characters=msg.response_characters,
                llm_profile_name=msg.llm_profile_name,
            )
            main_sequence = loop.loop.message_queue.accept(item, ready=False)

        return _AcceptedUserMessage(
            sequence=main_sequence,
            content=content,
            target_sessions=tuple(target_sessions),
        ), None

    async def _prepare_user_message(self, msg: Message, accepted: "_AcceptedUserMessage") -> None:
        """只处理已登记输入的后台准备：Profile 就绪、标题、客户端信息、子会话转发。

        非取消异常按 RV9 进入应用失败关闭；记录保留由关闭刷新只落 History。
        """
        from system.application import Application
        from system.llm_profile_store import LLMProfileStore
        from system.runtime import RuntimeSystem
        runtime = Application.current().get_system(RuntimeSystem)
        try:
            await self._prepare_user_message_inner(msg, accepted)
            if accepted.sequence is not None:
                loop = _get_loop(self.sid)
                if loop is None:
                    raise ApplicationStoppingError(
                        f"Main session loop disappeared before input ready: {self.sid}"
                    )
                loop.loop.message_queue.mark_ready(accepted.sequence)
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            runtime.record_failure(error)
            raise

    async def _prepare_user_message_inner(
        self, msg: Message, accepted: "_AcceptedUserMessage",
    ) -> None:
        if accepted.archived:
            await self._send_router_error(
                "This session has been archived. Please switch to the continuation session or create a new one."
            )
            return
        from system.application import Application
        from system.llm_profile_store import LLMProfileStore

        loop = _get_loop(self.sid)
        if loop is None:
            raise ApplicationStoppingError(f"Main session loop not ready: {self.sid}")

        content = accepted.content

        # 空闲主会话尽早切换；忙碌会话仅把名称保留到 FIFO 消息中。
        if "main" in accepted.target_sessions and not loop.loop.is_processing():
            store = Application.current().get_system(LLMProfileStore)
            with store.locked():
                selected = store.resolve_profile_name(msg.llm_profile_name or "")
                loop.set_profile(selected)

        self._auto_generate_title(content)
        _get_sm().update_last_activity(self.sid)

        # 提取前端携带的客户端信息并合并 IP
        if msg.client_info:
            sm = _get_sm()
            if sm is not None:
                existing = sm.get_client_info(self.sid)
                current_ip = existing.client_ip if existing else ""
                sm.set_client_info(self.sid, ClientInfo(
                    device_type=str(msg.client_info.get("device_type", "")),
                    browser=str(msg.client_info.get("browser", "")),
                    client_ip=current_ip,
                    frontend_version=str(msg.client_info.get("frontend_version", "")),
                    screen_orientation=str(msg.client_info.get("screen_orientation", "")),
                ))

        # 分派子 Agent 消息（父→子方向，不动）
        subagent_tasks, sub_ids, name_map = await self._dispatch_subagent_messages(
            content, list(accepted.target_sessions),
        )

        # 主会话：注册轮次后回调；输入记录已在接收阶段登记。
        if "main" in accepted.target_sessions:
            loop.set_on_round_done(self._make_on_round_done())

        # 等待子会话转发完成
        if subagent_tasks:
            results = await asyncio.gather(*subagent_tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, Exception):
                    logger.warning("Subagent forward failed: %s", res)

    async def handle_confirm_response(self, msg: Message) -> None:
        """处理审批响应。"""
        if msg.request_id is not None and msg.action is not None:
            logger.info("WS confirm response | session=%s request_id=%s action=%s", self.sid, msg.request_id, msg.action)
            from system.application import Application
            from entry.agent_sink import FrontendSink
            sink = Application.current().get_system(FrontendSink)
            sink.resolve_confirm(msg.request_id, msg.action, deny_reason=msg.deny_reason, denied_by=msg.denied_by or "user")

    async def handle_ask_response(self, msg: Message) -> None:
        """处理提问响应。"""
        if msg.request_id is not None:
            logger.info("WS ask response | session=%s request_id=%s", self.sid, msg.request_id)
            from system.application import Application
            from entry.agent_sink import FrontendSink
            sink = Application.current().get_system(FrontendSink)
            sink.resolve_ask(msg.request_id, option=msg.option, custom_text=msg.custom_text)

    async def handle_interrupt(self) -> None:
        """处理中断请求：与 HTTP 中断统一走 request_interrupt()。"""
        loop = _get_loop(self.sid)
        if loop is not None and loop.loop is not None:
            from system.application import Application
            from gateway.system import GatewaySystem
            task = Application.current().get_system(GatewaySystem).spawn_work(
                loop.request_interrupt(reason="user"),
                name=f"ws-interrupt-{self.sid[:8]}",
            )
            task.add_done_callback(_observe_background_interrupt)

    async def handle_disgust(self) -> None:
        """处理厌恶请求。"""
        logger.info("WS disgust | session=%s", self.sid)
        loop = _get_loop(self.sid)
        if loop is not None and loop.loop is not None:
            loop.loop.disgust()

    async def handle_file_upload(self, msg: Message) -> None:
        """处理文件上传：优先硬链接，fallback 到复制或 base64 解码。"""
        filename: str = (msg.filename or "uploaded_file").strip()
        mime_type: str = (msg.mime_type or "application/octet-stream").strip()
        file_data: str = (msg.file_data or "").strip()
        local_path: str | None = msg.local_path

        # 清理文件名中的路径遍历字符
        safe_name: str = filename.replace("\\", "/").split("/")[-1]
        if not safe_name:
            safe_name = "uploaded_file"

        timestamp: str = datetime.now(timezone.utc).strftime(UPLOAD_FILENAME_TIME_FORMAT)
        unique_name: str = f"{timestamp}_{uuid.uuid4().hex[:8]}_{safe_name}"

        from system.application import Application
        from system.runtime import RuntimeSystem
        agentspace_path: Path = (
            Application.current().get_system(RuntimeSystem).context.agentspace
        )
        upload_dir: Path = agentspace_path / UPLOADS_DIR_NAME
        upload_dir.mkdir(parents=True, exist_ok=True)
        dest: Path = upload_dir / unique_name

        # -- 硬链接优先 ----------------------------------------------------
        if local_path:
            src: Path = Path(local_path)
            if src.is_file():
                try:
                    os.link(str(src), str(dest))
                    logger.info("File hard-linked | session=%s src=%s dest=%s", self.sid, src, dest)
                    await self.ws.send_text(
                        json.dumps(
                            Message(
                                type=MessageType.SYSTEM,
                                session_id=self.sid,
                                content=json.dumps({
                                    "uploaded": True,
                                    "path": f"{UPLOADS_WS_PREFIX}{unique_name}",
                                    "filename": safe_name,
                                    "size": src.stat().st_size,
                                    "method": "hardlink",
                                }),
                            ).model_dump(exclude_none=True),
                            ensure_ascii=False,
                        )
                    )
                    return
                except OSError as exc:
                    logger.info("Hard link failed, fallback to copy | session=%s err=%s", self.sid, exc)
                    try:
                        shutil.copy2(str(src), str(dest))
                        logger.info("File copied (hardlink fallback) | session=%s src=%s dest=%s", self.sid, src, dest)
                        await self.ws.send_text(
                            json.dumps(
                                Message(
                                    type=MessageType.SYSTEM,
                                    session_id=self.sid,
                                    content=json.dumps({
                                        "uploaded": True,
                                        "path": f"{UPLOADS_WS_PREFIX}{unique_name}",
                                        "filename": safe_name,
                                        "size": src.stat().st_size,
                                        "method": "copy",
                                    }),
                                ).model_dump(exclude_none=True),
                                ensure_ascii=False,
                            )
                        )
                        return
                    except OSError as exc2:
                        logger.error("File copy also failed | session=%s err=%s", self.sid, exc2)
                        await self.ws.send_text(
                            json.dumps(
                                Message(
                                    type=MessageType.ERROR,
                                    session_id=self.sid,
                                    message=f"File link/copy failed: {exc2}",
                                ).model_dump(exclude_none=True),
                                ensure_ascii=False,
                            )
                        )
                        return

        # -- Base64 写入 ---------------------------------------------------
        if not file_data:
            await self.ws.send_text(
                json.dumps(
                    Message(
                        type=MessageType.ERROR,
                        session_id=self.sid,
                        message="File upload failed: file content is empty",
                    ).model_dump(exclude_none=True),
                    ensure_ascii=False,
                )
            )
            return

        try:
            raw_bytes: bytes = base64.b64decode(file_data)
            dest.write_bytes(raw_bytes)
        except Exception as exc:
            logger.exception("File upload failed for session=%s", self.sid)
            await self.ws.send_text(
                json.dumps(
                    Message(
                        type=MessageType.ERROR,
                        session_id=self.sid,
                        message=f"File save failed: {exc}",
                    ).model_dump(exclude_none=True),
                    ensure_ascii=False,
                )
            )
            return

        logical_path: str = f"{UPLOADS_WS_PREFIX}{unique_name}"
        logger.info("File uploaded (base64) | session=%s path=%s size=%d", self.sid, logical_path, len(raw_bytes))

        await self.ws.send_text(
            json.dumps(
                Message(
                    type=MessageType.SYSTEM,
                    session_id=self.sid,
                    content=json.dumps({
                        "uploaded": True,
                        "path": logical_path,
                        "filename": safe_name,
                        "mime_type": mime_type,
                        "size": len(raw_bytes),
                    }, ensure_ascii=False),
                ).model_dump(exclude_none=True),
                ensure_ascii=False,
            )
        )

    async def handle_handsfree_mode(self, msg: Message) -> None:
        """处理审批模式切换，回送服务端权威状态。"""
        from component.approval import set_approval_mode
        from entity.puretype import ApprovalMode

        mode_str = str(msg.content or "").strip().lower()
        try:
            mode = ApprovalMode(mode_str)
        except ValueError:
            mode = ApprovalMode.MANUAL
        actual = set_approval_mode(self.sid, mode)
        logger.info("Approval mode toggle | session=%s requested=%s actual=%s", self.sid, mode_str, actual.value)
        await self.ws.send_text(
            json.dumps(
                Message(
                    type=MessageType.HANDSFREE_MODE,
                    session_id=self.sid,
                    handsfree_mode=actual == ApprovalMode.HANDSFREE,
                    approval_mode=actual.value,
                ).model_dump(exclude_none=True),
                ensure_ascii=False,
            )
        )

    async def handle_ping(self) -> None:
        """处理心跳。"""
        await self.ws.send_text(
            json.dumps(
                Message(
                    type=MessageType.PONG,
                    session_id=self.sid,
                ).model_dump(exclude_none=True),
                ensure_ascii=False,
            )
        )

    async def handle_client_diagnostic(self, msg: Message) -> None:
        """记录脱敏客户端传输诊断，不写入聊天 History。"""
        diagnostic = msg.client_diagnostic
        if diagnostic is None:
            logger.warning(
                "Client diagnostic missing payload | session=%s",
                self.sid,
            )
            return
        logger.warning(
            "Client transport diagnostic | session=%s kind=%s phase=%s duration_ms=%d "
            "websocket_state=%s last_recv_age_ms=%s last_pong_age_ms=%s",
            self.sid,
            diagnostic.kind.value,
            diagnostic.phase.value,
            diagnostic.duration_ms,
            diagnostic.websocket_state,
            diagnostic.last_recv_age_ms,
            diagnostic.last_pong_age_ms,
        )

    async def handle_system_message(self, msg: Message) -> None:
        """处理系统消息（仅记录日志）。"""
        logger.info(
            "System message from session=%s: %s",
            self.sid, summarize_message_for_log(msg.content, max_text_len=None),
        )

    async def handle_unsupported(self, msg: Message) -> None:
        """处理不支持的消息类型。"""
        await self.ws.send_text(
            json.dumps(
                Message(
                    type=MessageType.ERROR,
                    session_id=self.sid,
                    message=f"Unsupported message type: {msg.type.value}",
                ).model_dump(exclude_none=True),
                ensure_ascii=False,
            )
        )

    # -- handle_user_message 子方法 ---------------------------------------

    def _auto_generate_title(self, content: Any) -> None:
        """从首条用户消息自动生成标题。"""
        session_info: SessionInfo | None = _get_sm().get(self.sid)
        if session_info and not session_info.title and content:
            text_content: str = _extract_text(content)
            title: str = text_content.strip()[:30]
            if len(text_content.strip()) > 30:
                title += "..."
            _get_sm().update_title(self.sid, title)

    async def _dispatch_subagent_messages(
        self, content: str, target_sessions: list[str],
    ) -> tuple[list[asyncio.Task], list[str], dict[str, str]]:
        """转发消息到子 Agent 会话。

        返回 (tasks, sub_ids, name_map)。
        """
        subagent_tasks: list[asyncio.Task] = []
        sub_ids: list[str] = []
        name_map: dict[str, str] = {}

        if not any(t != "main" for t in target_sessions):
            return subagent_tasks, sub_ids, name_map

        try:
            orch = get_subagent_orchestrator()
            sub_ids = [t for t in target_sessions if t != "main"]
            also_main = "main" in target_sessions

            from system.application import Application
            from gateway.system import GatewaySystem
            gateway = Application.current().get_system(GatewaySystem)

            # 建立 session_id → name 映射
            try:
                snapshot = orch.get_snapshot(parent_session_id=self.sid)
                for sess_id, info in snapshot.subagents.items():
                    name_map[sess_id] = info.name
            except Exception:
                logger.warning("Failed to get subagent snapshot for session=%s", self.sid, exc_info=True)

            for sub_id in sub_ids:
                other_ids = [o for o in sub_ids if o != sub_id]
                other_names: list[str] = []
                for o in other_ids:
                    name = name_map.get(o)
                    if name:
                        other_names.append(name)
                    else:
                        logger.warning(
                            "Skipping unnamed co-recipient session | parent=%s target=%s co_recipient=%s",
                            self.sid, sub_id, o,
                        )
                if also_main:
                    other_names.append("the Parent Agent (main session)")
                subagent_tasks.append(
                    gateway.spawn_work(
                        orch.chat_user_direct(
                            parent_session_id=self.sid,
                            session_id=sub_id,
                            message=str(content),
                            co_recipients=other_names,
                        ),
                        name=f"user-to-subagent-{sub_id[:16]}",
                    )
                )
        except Exception as exc:
            logger.warning("Failed to dispatch subagent messages: %s", exc)

        return subagent_tasks, sub_ids, name_map

    # -- SP-5 D2：轮次后编排回调 ------------------------------------------

    async def _on_round_done_cb(self, loop: IMainSessionLoop) -> None:
        """轮次后编排：WS 重映射 + token 推送 + 正典历史同步。

        由 run_pending_round 锁外末尾调用；回复推送已由 run_pending_round 内部
        emit_assistant_message 覆盖（parent 版），multi 版各 agent 独立流式推送。
        进化关闭由 Loop 在工具结果严格保存后自行请求，不再经 Gateway 文本回调。
        """
        await self._handle_session_rotation(loop)
        await self._send_token_update(loop)
        await self._send_history_sync(loop)

    def _make_on_round_done(self):
        """返回捕获 self 的 async callable（幂等覆盖；WS 重连时新 router 覆盖注册）。

        R3 缓解：lambda 捕获 MessageRouter 实例而非持有 router 引用，
        新 router 覆盖注册后旧实例随 lambda 替换可 GC。
        """
        async def _cb(loop):
            await self._on_round_done_cb(loop)
        return _cb

    async def _handle_session_rotation(self, loop: IMainSessionLoop) -> None:
        """检查并处理会话旋转（归档+新会话），更新 self.sid 和 WebSocket 映射。"""
        _old: str = self.sid
        _rotated: str | None = loop.pop_session_rotated()
        if not _rotated:
            return

        from system.application import Application
        from entry.agent_sink import FrontendSink
        sink = Application.current().get_system(FrontendSink)
        sink.unregister_ws(_old)
        sink.register_ws(_rotated, self.ws, self.conn_token)
        self.sid = _rotated

        try:
            await self.ws.send_text(
                Message(
                    type=MessageType.SYSTEM,
                    session_id=self.sid,
                    content=json.dumps({
                        "action": "session_rotated",
                        "new_sid": self.sid,
                        "old_sid": _old,
                    }),
                ).model_dump_json(exclude_none=True)
            )
        except Exception:
            logger.debug(
                "Failed to send session_rotated notification for old=%s new=%s",
                _old, self.sid, exc_info=True,
            )

    async def _emit_assistant_reply(self, loop: IMainSessionLoop, reply: str) -> None:
        """发送 assistant 回复到前端。MultiAgentLoop 空回复跳过。"""
        if not reply:
            return
        from system.application import Application
        from entry.agent_sink import FrontendSink
        sink = Application.current().get_system(FrontendSink)
        await sink.emit_assistant_message(
            self.sid, reply, loop.current_character_agent,
        )

    async def _send_history_sync(self, loop: IMainSessionLoop) -> None:
        """在一轮 History 写入完成后推送正典历史同步元数据。"""
        # agents 是会话级模式状态，必须按会话当前注册 Loop 计算：轮次所属 Loop
        # 可能已被 replace_loop 退役（如 ExitMultiAgent），沿用退役 MultiAgentLoop
        # 的参与者列表会把 ExitMultiAgent 推送的清空通知重新覆盖为过期列表。
        # 与 server.py 握手处 HISTORY_SYNC 的口径保持一致。
        agents_info: list[str] | None = None
        current_loop = _get_loop(self.sid)
        if current_loop is not None:
            from entry.multi_agent_loop import MultiAgentLoop
            if isinstance(current_loop, MultiAgentLoop):
                agents_info = list(current_loop.get_agents().keys())
        try:
            await self.ws.send_text(
                json.dumps(
                    Message(
                        type=MessageType.HISTORY_SYNC,
                        session_id=self.sid,
                        history_count=loop.loop.history.count,
                        processing=loop.loop.is_active(),
                        token_usage=loop.get_token_usage(),
                        context_tokens=loop.get_context_tokens(),
                        agents=agents_info,
                    ).model_dump(exclude_none=True),
                    ensure_ascii=False,
                )
            )
        except Exception:
            logger.debug(
                "Failed to send history_sync for session=%s",
                self.sid,
                exc_info=True,
            )

    async def _send_token_update(self, loop: IMainSessionLoop) -> None:
        """向前端发送实时 token 消耗更新。

        复用 FrontendSink.emit_usage_update()，统一走 sink 的连接检查
        （get_ws None 短路）与 warning 级别错误降级，避免 WebSocket 已关闭后
        send_text 触发 RuntimeError 并产生 ERROR 级 traceback 噪声。
        """
        from system.application import Application
        from entry.agent_sink import FrontendSink
        sink = Application.current().get_system(FrontendSink)
        await sink.emit_usage_update(
            self.sid, loop.get_token_usage(), loop.get_context_tokens(),
        )