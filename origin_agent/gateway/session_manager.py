"""SessionManager — 管理 session 生命周期与 ParentAgentLoop 映射。

从 gateway/server.py 的全局变量和 HTTP 端点逻辑中抽出。
通过 Application.current() 访问单例，替代模块级 sessions 全局变量。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

from gateway.chat import SessionManager as ChatSessionManager
from entity.puretype import Loop, LoopMeta
from system.session_store import SessionStore

if TYPE_CHECKING:
    from entry.base_agent_loop import IMainSessionLoop
    from entry.multi_agent_loop import MultiAgentLoop

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
        self._loops: dict[str, IMainSessionLoop] = {}
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
        self, context: str, parent_sid: str | None = None, role: str = "user",
        loop_meta: LoopMeta | None = None,
    ) -> str:
        return self._chat_sm.create_with_context(
            context, parent_sid=parent_sid, role=role, loop_meta=loop_meta,
        )

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

    def get_all_loops(self) -> dict[str, IMainSessionLoop]:
        """返回所有活跃 loop 的 (session_id → IMainSessionLoop) 快照。"""
        return dict(self._loops)

    # -- ParentAgentLoop 管理 --

    def create_session(
        self,
        session_id: str,
        frontend_sink,
        history_store_dir: Path | None = None,
    ) -> IMainSessionLoop:
        """为 session 创建或复用 loop 实例。

        若已有活跃的 loop 实例则直接返回（WebSocket 重连场景，
        可能是 ParentAgentLoop 或 MultiAgentLoop），否则根据索引
        中的 loop_type 创建对应的 loop 实例。
        """
        # 已有 loop 则复用（可能是 MultiAgentLoop，因 replace_loop 已替换）
        existing = self._loops.get(session_id)
        if existing is not None:
            logger.debug("Reusing existing loop for session=%s: %s", session_id, type(existing).__name__)
            return existing

        # 读取索引 loop_type，若为 multi 则创建 MultiAgentLoop
        info = self._chat_sm.get(session_id)
        if info and info.get("loop_type") == Loop.multi.value:
            return self._create_multi_loop(session_id, frontend_sink, history_store_dir)

        # 默认创建 ParentAgentLoop
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
            self._app.cron_router.register(session_id, loop.loop)

        return loop

    def _create_multi_loop(
        self,
        session_id: str,
        frontend_sink,
        history_store_dir: Path | None = None,
    ) -> IMainSessionLoop:
        """根据索引中的 LoopMeta 重建 MultiAgentLoop。"""
        from system.context import get_runtime_context
        from component.mutliagenttools._store import SubagentStore
        from component.llm import LLMClient
        from entry.multi_agent_loop import MultiAgentLoop
        from system.templates import get_templates_dir
        from abstract.tools.registry import registry as tool_registry
        from entity.constant import MAIN_AGENT_CHARACTER_NAME
        from system.sandbox import Sandbox
        from component.mutliagenttools.profile_builder import (
            build_multi_agent_tools,
            build_agent_profiles,
        )

        info = self._chat_sm.get(session_id)
        agents_names: list[str] = (info.get("agents") or []) if info else []

        parent_ctx = get_runtime_context()
        sandbox = Sandbox(parent_ctx)
        store = SubagentStore(parent_ctx.agentspace)

        # 加载多 Agent 系统提示词模板
        template_path = get_templates_dir() / "multiagent" / "multi_agent_system_prompt.txt"
        with open(template_path, "r", encoding="utf-8") as f:
            system_prompt_template = f.read()

        # 工具集：排除 multiagent 工具集
        tools = build_multi_agent_tools(tool_registry)

        agent_profiles = build_agent_profiles(
            agents=agents_names,
            main_agent_name=MAIN_AGENT_CHARACTER_NAME,
            parent_ctx=parent_ctx,
            llm_client_factory=lambda name, profile: (
                LLMClient(parent_ctx) if name == MAIN_AGENT_CHARACTER_NAME
                else LLMClient(parent_ctx.model_copy(update={
                    "llm_api_key": profile.get("api_key") or parent_ctx.llm_api_key,
                    "llm_base_url": profile.get("base_url", parent_ctx.llm_base_url),
                    "llm_model": profile.get("model", parent_ctx.llm_model),
                    "llm_max_output_tokens": profile.get("max_output_tokens", parent_ctx.llm_max_output_tokens),
                    "llm_max_context_tokens": profile.get("max_context_tokens", parent_ctx.llm_max_context_tokens),
                    "llm_temperature": parent_ctx.llm_temperature,
                }))
            ),
            system_prompt_template=system_prompt_template,
            sandbox=sandbox,
            store=store,
            session_id=session_id,
            skip_missing_subagent=True,
        )

        # 回填统一 tools
        for profile in agent_profiles.values():
            profile.tools = tools

        if not agent_profiles:
            logger.error(
                "No valid agent profiles found for multi session=%s; falling back to ParentAgentLoop",
                session_id,
            )
            from entry.parent_agent_loop import ParentAgentLoop
            loop = ParentAgentLoop(
                app=self._app,
                session_id=session_id,
                frontend_sink=frontend_sink,
                history_store_dir=history_store_dir,
            )
            loop.set_session_manager(self)
            self._loops[session_id] = loop
            if self._app.cron_router is not None:
                self._app.cron_router.register(session_id, loop)
            return loop

        # 读取 history.es
        ss = SessionStore(history_store_dir) if history_store_dir else None
        history = None
        if ss is not None:
            history = ss.read_history(session_id)

        from entity.messages import History
        if history is None:
            history = History(messages=[])

        multi_loop: MultiAgentLoop = MultiAgentLoop(
            app=self._app,
            session_id=session_id,
            history=history,
            agents=agent_profiles,
            sink=frontend_sink,
            history_store_dir=history_store_dir,
        )
        self._loops[session_id] = multi_loop
        if self._app.cron_router is not None:
            self._app.cron_router.register(session_id, multi_loop)
        return multi_loop

    def get_loop(self, session_id: str) -> IMainSessionLoop | None:
        """返回指定 session 的 IMainSessionLoop。"""
        return self._loops.get(session_id)

    def terminate_session(self, session_id: str) -> None:
        """终止 session：中断 loop 并清理。"""
        loop = self._loops.pop(session_id, None)
        if loop is not None:
            loop.loop.interrupt()
            if self._app.cron_router is not None:
                self._app.cron_router.unregister(session_id)
            logger.info("Session terminated: %s", session_id)

    async def replace_loop(self, session_id: str, new_loop: IMainSessionLoop) -> None:
        """将 session 的当前 loop 替换为 new_loop（不可逆）。

        旧 loop 被 interrupt 并从映射中移除；新 loop 继承 session_id
        并重新注册到 CronRouter（如有需要）。同时更新索引中的 LoopMeta。

        若 session_id 不在当前映射中，则直接注册新 loop。
        """
        old_loop = self._loops.pop(session_id, None)
        if old_loop is not None:
            old_loop.loop.interrupt()
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

        new_loop.loop.session_id = session_id
        self._loops[session_id] = new_loop

        if self._app.cron_router is not None:
            self._app.cron_router.register(session_id, new_loop.loop)

        # 更新索引中的 LoopMeta
        from entry.multi_agent_loop import MultiAgentLoop
        if isinstance(new_loop, MultiAgentLoop):
            agents = list(new_loop._agents.keys())
            self._chat_sm.update_loop_type(session_id, Loop.multi.value, agents)
            # 通知前端 agents 列表已变更
            try:
                sink = self._app.frontend_sink
                if sink is not None:
                    import json as _json
                    ws = sink.get_ws(session_id)
                    if ws is not None:
                        await ws.send_text(_json.dumps({
                            "type": "system",
                            "session_id": session_id,
                            "content": _json.dumps({"agents": agents}),
                        }, ensure_ascii=False))
            except Exception:
                logger.warning("Failed to push agents for session=%s", session_id, exc_info=True)
        else:
            self._chat_sm.update_loop_type(session_id, Loop.parent.value)

    def rotate_session(self, old_sid: str, new_sid: str) -> None:
        """旋转 session：将 loop 从旧 ID 迁移到新 ID。"""
        loop = self._loops.pop(old_sid, None)
        if loop is not None:
            if self._app.cron_router is not None:
                self._app.cron_router.unregister(old_sid)
            loop.loop.session_id = new_sid
            self._loops[new_sid] = loop
            if self._app.cron_router is not None:
                self._app.cron_router.register(new_sid, loop.loop)
            logger.info("Session rotated: %s → %s", old_sid, new_sid)