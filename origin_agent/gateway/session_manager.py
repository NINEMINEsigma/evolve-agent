"""SessionManager — 管理 session 生命周期与 ParentAgentLoop 映射。

从 gateway/server.py 的全局变量和 HTTP 端点逻辑中抽出。
通过 Application.current() 访问单例，替代模块级 sessions 全局变量。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

from gateway.chat import SessionManager as ChatSessionManager

if TYPE_CHECKING:
    from entry.parent_agent_loop import ParentAgentLoop
    from entry.base_agent_loop import BaseAgentLoop

logger = logging.getLogger(__name__)


class SessionManager:
    """Session 生命周期管理 + ParentAgentLoop 映射。

    持有：
    - _chat_sm: 底层的 chat.SessionManager（持久化、TTL、标签）
    - _loops: session_id → ParentAgentLoop 映射

    方法：
    - create_session(session_id, frontend_sink, history_store_dir) → ParentAgentLoop
    - get_loop(session_id) → ParentAgentLoop | None
    - terminate_session(session_id)
    - archive_session(session_id)
    - rotate_session(old_sid, new_sid)
    """

    def __init__(self, store_path: str | None = None):
        from system.application import Application

        self._app = Application.current()
        self._chat_sm = ChatSessionManager(store_path)
        self._loops: dict[str, BaseAgentLoop] = {}
        self._store_path: str | None = store_path

    # -- 委托给底层 ChatSessionManager 的方法 --

    @property
    def chat_manager(self) -> ChatSessionManager:
        return self._chat_sm

    def get(self, session_id: str) -> dict | None:
        """返回 session 元数据（兼容旧接口）。"""
        return self._chat_sm.get(session_id)

    def get_all(self) -> list[dict]:
        return self._chat_sm.get_all()

    def create_with_context(
        self, context: str, parent_sid: str | None = None, role: str = "user"
    ) -> str:
        return self._chat_sm.create_with_context(context, parent_sid=parent_sid, role=role)

    def archive(self, session_id: str, continuation_sid: str | None = None) -> None:
        self._chat_sm.archive(session_id, continuation_sid=continuation_sid)

    def set_session_tags(self, session_id: str, tags: list[str]) -> None:
        self._chat_sm.set_session_tags(session_id, tags)

    def set_store_dir(self, path: str) -> None:
        self._chat_sm.set_store_dir(path)

    def get_all_tags(self) -> list[str]:
        return self._chat_sm.get_all_tags()

    # TODO: 不健壮的方法
    def __getattr__(self, name: str) -> Any:
        """未显式定义的方法委托给底层的 ChatSessionManager。"""
        return getattr(self._chat_sm, name)

    def get_all_loops(self) -> dict[str, BaseAgentLoop]:
        """返回所有活跃 loop 的 (session_id → BaseAgentLoop) 快照。"""
        return dict(self._loops)

    # -- ParentAgentLoop 管理 --

    def create_session(
        self,
        session_id: str,
        frontend_sink,
        history_store_dir: Path | None = None,
    ) -> BaseAgentLoop:
        """为 session 创建或复用 loop 实例。

        若已有活跃的 loop 实例则直接返回（WebSocket 重连场景，
        可能是 ParentAgentLoop 或 MultiAgentLoop），否则创建新的 ParentAgentLoop。
        """
        # 已有 loop 则复用（可能是 MultiAgentLoop，因 replace_loop 已替换）
        existing = self._loops.get(session_id)
        if existing is not None:
            logger.debug("Reusing existing loop for session=%s: %s", session_id, type(existing).__name__)
            return existing

        from entry.parent_agent_loop import ParentAgentLoop

        loop = ParentAgentLoop(
            app=self._app,
            session_id=session_id,
            frontend_sink=frontend_sink,
            history_store_dir=history_store_dir,
        )
        loop.set_session_manager(self)
        self._loops[session_id] = loop

        # 注册到 CronRouter，使 cron 结果能投递到该 loop 的 inbox
        if self._app.cron_router is not None:
            self._app.cron_router.register(session_id, loop)

        return loop

    def get_loop(self, session_id: str) -> BaseAgentLoop | None:
        """返回指定 session 的 BaseAgentLoop。"""
        return self._loops.get(session_id)

    def terminate_session(self, session_id: str) -> None:
        """终止 session：中断 loop 并清理。"""
        loop = self._loops.pop(session_id, None)
        if loop is not None:
            loop.interrupt()
            if self._app.cron_router is not None:
                self._app.cron_router.unregister(session_id)
            logger.info("Session terminated: %s", session_id)

    def replace_loop(self, session_id: str, new_loop: BaseAgentLoop) -> None:
        """将 session 的当前 loop 替换为 new_loop（不可逆）。

        旧 loop 被 interrupt 并从映射中移除；新 loop 继承 session_id
        并重新注册到 CronRouter（如有需要）。

        若 session_id 不在当前映射中，则直接注册新 loop。
        """
        old_loop = self._loops.pop(session_id, None)
        if old_loop is not None:
            old_loop.interrupt()
            if self._app.cron_router is not None:
                self._app.cron_router.unregister(session_id)
            logger.info(
                "Loop replaced for session=%s: %s → %s",
                session_id,
                type(old_loop).__name__,
                type(new_loop).__name__,
            )
        else:
            logger.info(
                "Registering new loop for session=%s: %s",
                session_id,
                type(new_loop).__name__,
            )

        new_loop.session_id = session_id
        self._loops[session_id] = new_loop

        if self._app.cron_router is not None:
            self._app.cron_router.register(session_id, new_loop)

    def rotate_session(self, old_sid: str, new_sid: str) -> None:
        """旋转 session：将 loop 从旧 ID 迁移到新 ID。"""
        loop = self._loops.pop(old_sid, None)
        if loop is not None:
            if self._app.cron_router is not None:
                self._app.cron_router.unregister(old_sid)
            loop.session_id = new_sid
            self._loops[new_sid] = loop
            if self._app.cron_router is not None:
                self._app.cron_router.register(new_sid, loop)
            logger.info("Session rotated: %s → %s", old_sid, new_sid)