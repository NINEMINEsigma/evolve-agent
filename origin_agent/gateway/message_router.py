"""消息路由：将 WebSocket 消息按类型分发到对应的处理方法。

从 gateway/server.py 的 ws_chat 拆分而来，负责所有消息类型的处理逻辑。
ws_chat 仅保留 WebSocket 连接生命周期管理，通过 ``MessageRouter.route()``
委托消息处理。

消息类型与处理方法映射：
    USER_MESSAGE      → handle_user_message（后台 task）
    CONFIRM_RESPONSE  → handle_confirm_response
    ASK_RESPONSE      → handle_ask_response
    INTERRUPT         → handle_interrupt
    FILE_UPLOAD       → handle_file_upload
    HANDSFREE_MODE    → handle_handsfree_mode
    PING              → handle_ping
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
from datetime import datetime, timezone
from pathlib import Path
from typing import *

from fastapi import WebSocket

from .chat import Message, MessageType
from entity.constant import UPLOAD_FILENAME_TIME_FORMAT, UPLOADS_DIR_NAME, UPLOADS_WS_PREFIX
from entity.puretype import SessionInfo, SessionStatus

if TYPE_CHECKING:
    from entry.parent_agent_loop import ParentAgentLoop
    from entry.multi_agent_loop import MultiAgentLoop
    from entry.base_agent_loop import IMainSessionLoop
    from gateway.session_manager import SessionManager
    from subagent.orchestrator import SubAgentOrchestrator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 模块级辅助函数 — 从 server.py 复制，避免循环导入
# ---------------------------------------------------------------------------


def _get_sm() -> SessionManager | None:
    """返回 Application 的 SessionManager。"""
    from system.application import Application
    return Application.current().session_manager


def _get_loop(session_id: str) -> ParentAgentLoop | MultiAgentLoop | None:
    """返回指定 session 的 BaseAgentLoop（实际为 ParentAgentLoop 或 MultiAgentLoop）。"""
    sm = _get_sm()
    return sm.get_loop(session_id) if sm else None


def _get_ws(session_id: str) -> WebSocket | None:
    """返回指定 session 的 WebSocket sink。"""
    from system.application import Application
    sink = Application.current().frontend_sink
    return sink.get_ws(session_id) if sink else None


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
    return Application.current().subagent_orchestrator


# ---------------------------------------------------------------------------
# MessageRouter
# ---------------------------------------------------------------------------


class MessageRouter:
    """消息路由：将 WebSocket 消息按类型分发到对应的处理方法。

    ``ws_chat`` 在连接建立后创建本实例，消息循环中调用 ``route()`` 分发。
    实例持有 WebSocket 引用和当前 session_id（session 旋转时会更新）。
    """

    def __init__(self, ws: WebSocket, sid: str, agentspace_path: Path | None = None):
        self.ws = ws
        self.sid = sid
        self.agentspace_path = agentspace_path

    # -- 主分发入口 --------------------------------------------------------

    async def route(self, msg: Message) -> bool:
        """按消息类型分发到对应的处理方法。

        返回 False 表示消息循环应终止（如 agent loop 未就绪时）。"""
        msg.session_id = self.sid  # 信任 server 而非 client

        if msg.type == MessageType.USER_MESSAGE:
            if _get_loop(self.sid) is None:
                logger.error("ParentAgentLoop not configured; cannot handle chat messages")
                await self.ws.send_text(
                    json.dumps(
                        Message(
                            type=MessageType.ERROR,
                            session_id=self.sid,
                            message="Agent loop not ready. Please wait and try again.",
                        ).model_dump(exclude_none=True),
                        ensure_ascii=False,
                    )
                )
                return False
            # 后台执行，不阻塞 WebSocket 消息循环
            asyncio.create_task(
                self.handle_user_message(msg),
                name=f"user-msg-{self.sid[:8]}",
            )

        elif msg.type == MessageType.CONFIRM_RESPONSE:
            await self.handle_confirm_response(msg)

        elif msg.type == MessageType.ASK_RESPONSE:
            await self.handle_ask_response(msg)

        elif msg.type == MessageType.INTERRUPT:
            await self.handle_interrupt()

        elif msg.type == MessageType.FILE_UPLOAD:
            await self.handle_file_upload(msg)

        elif msg.type == MessageType.HANDSFREE_MODE:
            await self.handle_handsfree_mode(msg)

        elif msg.type == MessageType.PING:
            await self.handle_ping()

        elif msg.type == MessageType.SYSTEM:
            await self.handle_system_message(msg)

        else:
            await self.handle_unsupported(msg)

        return True

    # -- 消息处理方法 ------------------------------------------------------

    async def handle_user_message(self, msg: Message) -> None:
        """处理用户消息：自动标题、归档检查、子Agent转发、主会话处理。

        此方法作为后台 task 运行，不阻塞 WebSocket 消息循环。
        session 旋转时会更新 ``self.sid``。
        """
        try:
            self._auto_generate_title(msg.content)
            _get_sm().update_last_activity(self.sid)

            # 拦截 archived 会话的新消息
            session_info = _get_sm().get(self.sid)
            if session_info and session_info.status == SessionStatus.archived:
                await self.ws.send_text(
                    json.dumps(
                        Message(
                            type=MessageType.ERROR,
                            session_id=self.sid,
                            message="This session has been archived. Please switch to the continuation session or create a new one.",
                        ).model_dump(exclude_none=True),
                        ensure_ascii=False,
                    )
                )
                return

            loop = _get_loop(self.sid)
            if loop is None:
                return

            target_sessions: list[str] = msg.target_sessions or ["main"]
            content = msg.content or ""

            # 把原始用户消息追加到历史
            try:
                await loop.append_user_message(
                    content,
                    visible_characters=msg.visible_characters,
                    response_characters=msg.response_characters,
                    client_message_id=msg.client_message_id,
                )
            except Exception as exc:
                logger.warning("Failed to append user message for session=%s: %s", self.sid, exc)

            # 分派子 Agent 消息
            subagent_tasks, sub_ids, name_map = await self._dispatch_subagent_messages(
                content, target_sessions,
            )

            # 主会话处理
            reply = await self._process_main_session(
                loop, content, msg, target_sessions, sub_ids, name_map,
            )

            # 等待子会话转发完成
            if subagent_tasks:
                results = await asyncio.gather(*subagent_tasks, return_exceptions=True)
                for idx, res in enumerate(results):
                    if isinstance(res, Exception):
                        logger.warning("Subagent forward failed: %s", res)

            # 检查 session 旋转
            await self._handle_session_rotation(loop)

            # 发送 assistant 回复
            await self._emit_assistant_reply(loop, reply)

            # 发送 token 更新
            await self._send_token_update(loop)

            # 检查进化触发
            from main import trigger_evolution_shutdown
            trigger_evolution_shutdown()

        except Exception as exc:
            logger.exception("User message handler error for session=%s: %s", self.sid, exc)

    async def handle_confirm_response(self, msg: Message) -> None:
        """处理审批响应。"""
        if msg.request_id is not None and msg.action is not None:
            logger.info("WS confirm response | session=%s request_id=%s action=%s", self.sid, msg.request_id, msg.action)
            from system.application import Application
            sink = Application.current().frontend_sink
            if sink:
                sink.resolve_confirm(msg.request_id, msg.action, deny_reason=msg.deny_reason, denied_by=msg.denied_by or "user")

    async def handle_ask_response(self, msg: Message) -> None:
        """处理提问响应。"""
        if msg.request_id is not None:
            logger.info("WS ask response | session=%s request_id=%s", self.sid, msg.request_id)
            from system.application import Application
            sink = Application.current().frontend_sink
            if sink:
                sink.resolve_ask(msg.request_id, option=msg.option, custom_text=msg.custom_text)

    async def handle_interrupt(self) -> None:
        """处理中断请求。"""
        logger.info("WS interrupt | session=%s", self.sid)
        loop = _get_loop(self.sid)
        if loop is not None:
            loop.interrupt()

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

        if not self.agentspace_path:
            logger.error("agentspace path not set, cannot accept file uploads")
            await self.ws.send_text(
                json.dumps(
                    Message(
                        type=MessageType.SYSTEM,
                        session_id=self.sid,
                        content=json.dumps({"uploaded": False, "error": "agentspace_not_configured"}),
                    ).model_dump(exclude_none=True),
                    ensure_ascii=False,
                )
            )
            return

        upload_dir: Path = self.agentspace_path / UPLOADS_DIR_NAME
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
        """处理脱手模式切换。"""
        from component.approval import set_handsfree_mode
        enabled = msg.content is not None and (str(msg.content).lower() in ("true", "1", "on"))
        logger.info("Handsfree mode toggle | session=%s enabled=%s", self.sid, enabled)
        set_handsfree_mode(self.sid, enabled)

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

    async def handle_system_message(self, msg: Message) -> None:
        """处理系统消息（仅记录日志）。"""
        logger.info("System message from session=%s: %s", self.sid, msg.content)

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

            # 建立 session_id → name 映射
            try:
                snapshot = orch.get_snapshot(parent_session_id=self.sid)
                for sess_id, info in snapshot.items():
                    name_map[sess_id] = info.get("name", "")
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
                    asyncio.create_task(
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

    async def _process_main_session(
        self,
        loop: ParentAgentLoop | MultiAgentLoop,
        content: str,
        msg: Message,
        target_sessions: list[str],
        sub_ids: list[str],
        name_map: dict[str, str],
    ) -> str:
        """处理主会话的消息。返回 agent 回复文本。"""
        if "main" not in target_sessions:
            return "Message forwarded to sub-agent(s)."

        main_content = content
        sub_names: list[str] = []
        for s in sub_ids:
            name = name_map.get(s)
            if name:
                sub_names.append(name)
            else:
                logger.warning(
                    "Skipping unnamed sub-agent target for main session | parent=%s target=%s",
                    self.sid, s,
                )
        if sub_names:
            main_content = (
                f"[This message is also shared with sub-agents: {', '.join(sub_names)}]\n\n"
                f"{content}"
            )
        try:
            reply = await loop.process_message(
                main_content,
                skip_append=True,
                visible_characters=msg.visible_characters,
                response_characters=msg.response_characters,
            )
        except Exception as exc:
            logger.exception("Agent loop error for session=%s", self.sid)
            reply = f"Internal error: {exc}"

        return reply

    async def _handle_session_rotation(self, loop: IMainSessionLoop) -> None:
        """检查并处理会话旋转（归档+新会话），更新 self.sid 和 WebSocket 映射。"""
        _old: str = self.sid
        _rotated: str | None = loop.pop_session_rotated()
        if not _rotated:
            return

        from system.application import Application
        sink = Application.current().frontend_sink
        if sink:
            sink.unregister_ws(_old)
            sink.register_ws(_rotated, self.ws)
        self.sid = _rotated

        await self.ws.send_text(
            json.dumps(
                Message(
                    type=MessageType.SYSTEM,
                    content=json.dumps({
                        "action": "session_rotated",
                        "new_sid": self.sid,
                        "old_sid": _old,
                    }),
                ).model_dump(exclude_none=True),
                ensure_ascii=False,
            )
        )

    async def _emit_assistant_reply(self, loop: ParentAgentLoop | MultiAgentLoop, reply: str) -> None:
        """发送 assistant 回复到前端。MultiAgentLoop 空回复跳过。"""
        if not reply:
            return
        from system.application import Application
        sink = Application.current().frontend_sink
        if sink is not None:
            await sink.emit_assistant_message(
                self.sid, reply, loop.current_character_agent,
            )

    async def _send_token_update(self, loop: IMainSessionLoop) -> None:
        """向前端发送实时 token 消耗更新。"""
        try:
            await self.ws.send_text(
                json.dumps(
                    Message(
                        type=MessageType.SYSTEM,
                        session_id=self.sid,
                        content=json.dumps({
                            "token_usage": loop.get_token_usage(),
                            "context_tokens": loop.get_context_tokens(),
                        }),
                    ).model_dump(exclude_none=True),
                    ensure_ascii=False,
                )
            )
        except Exception:
            logger.exception("Failed to send token usage update for session=%s", self.sid)