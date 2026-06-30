"""Application 唯一全局单例 — 装配所有子系统。

所有业务对象通过 Application.current() 访问，避免模块级全局变量。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from system.context import RuntimeContext
    from gateway.session_manager import SessionManager
    from component.approval import ApprovalBackend
    from component.cron_router import CronRouter
    from abstract.tools.registry import ToolRegistry
    from entry.base_agent_loop import BaseAgentLoop
    from entry.agent_sink import FrontendSink
    from subagent.orchestrator import SubAgentOrchestrator

logger = logging.getLogger(__name__)

# 模块级引用，指向运行中的 Application 实例。
_app: Application | None = None


class Application:
    """进程级唯一单例，持有所有子系统引用。

    用法::

        app = Application(runtime_ctx)
        # 装配子系统
        app.session_manager = SessionManager(app)
        # 访问依赖
        loop = Application.current().session_manager.get_loop(sid)
    """

    def __init__(self, runtime_context: RuntimeContext) -> None:
        global _app
        self.runtime_context:           RuntimeContext = runtime_context

        # -- 子系统（由启动流程装配） --
        self.session_manager:           SessionManager | None = None
        self.approval_backend_manager:  ApprovalBackendManager | None = None
        self.cron_router:               CronRouter | None = None
        self.tool_registry:             ToolRegistry | None = None
        self.frontend_sink:             FrontendSink | None = None
        self.subagent_orchestrator:     SubAgentOrchestrator | None = None

        # -- 关闭信号（与 main.py 的 App 共享） --
        self._shutdown_event:           object | None = None  # asyncio.Event

        _app = self

    @staticmethod
    def current() -> Application:
        """返回当前进程的 Application 单例。"""
        global _app
        if _app is None:
            raise RuntimeError("Application not initialized — call Application(ctx) first")
        return _app

    def link_shutdown_event(self, event: object) -> None:
        """绑定 main.py App 的关闭事件，供子系统优雅退出使用。"""
        self._shutdown_event = event

    async def shutdown(self) -> None:
        """按依赖顺序停止子系统。"""
        logger.info("Application shutdown initiated")
        # 1. 停止 cron 后台任务
        if self.cron_router is not None:
            try:
                await self.cron_router.shutdown()
            except Exception as exc:
                logger.warning("CronRouter shutdown failed: %s", exc)
        # 2. 停止审批后端
        if self.approval_backend_manager is not None:
            try:
                await self.approval_backend_manager.shutdown()
            except Exception as exc:
                logger.warning("ApprovalBackendManager shutdown failed: %s", exc)
        logger.info("Application shutdown complete")


class ApprovalBackendManager:
    """管理审批后端的懒加载和生命周期。

    从 component/approval.py 迁移出来，避免该模块持有全局状态。
    """

    def __init__(self, ctx: RuntimeContext) -> None:
        self._ctx = ctx
        self._backend: ApprovalBackend | None = None
        self._failed: bool = False

    def get_backend(self) -> ApprovalBackend | None:
        """懒加载审批后端。返回 None 表示不可用。"""
        if self._failed:
            return None
        if self._backend is not None:
            return self._backend

        from component.approval import _create_approval_backend
        self._backend = _create_approval_backend(self._ctx)
        if self._backend is None:
            self._failed = True
        return self._backend

    async def shutdown(self) -> None:
        """停止审批后端子进程。"""
        try:
            from component.approval import shutdown_approval_model
            shutdown_approval_model()
        except Exception:
            pass
        self._backend = None