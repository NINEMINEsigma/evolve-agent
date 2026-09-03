"""Application 唯一全局单例 — 装配所有子系统。

所有业务对象通过 Application.current() 访问，避免模块级全局变量。
子系统在 init() 中 eager 初始化，通过 @property 只读暴露，防止意外赋值。
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from entity.puretype import ApprovalProfileState
    from system.context import RuntimeContext
    from system.llm_profile_store import LLMProfileStore
    from system.sandbox import Sandbox
    from system.agentspace import AgentspaceService
    from gateway.session_manager import SessionManager
    from component.approval.backend import ApprovalBackend
    from component.cron_router import CronRouter
    from abstract.tools.registry import ToolRegistry
    from entry.agent_sink import FrontendSink
    from subagent.orchestrator import SubAgentOrchestrator

logger = logging.getLogger(__name__)

# 模块级引用，指向运行中的 Application 实例。
_app: Application | None = None


class Application:
    """进程级唯一单例，持有所有子系统引用。

    用法::

        app = Application(runtime_ctx)
        app.init()           # 构造后立刻调用，初始化所有子系统
        # 后续通过 app.cron_router / app.session_manager 等只读访问
    """

    def __init__(self, runtime_context: RuntimeContext) -> None:
        global _app
        self.runtime_context: RuntimeContext = runtime_context

        # -- 子系统 private fields（由 init() 创建，@property 只读暴露）--
        self._profile_lock:              threading.RLock = threading.RLock()
        self._llm_profile_store:         LLMProfileStore | None = None
        self._sandbox:                   Sandbox | None = None
        self._agentspace_service:        AgentspaceService | None = None
        self._cron_router:               CronRouter | None = None
        self._session_manager:           SessionManager | None = None
        self._frontend_sink:             FrontendSink | None = None
        self._approval_backend_manager:  ApprovalBackendManager | None = None

        # -- 外部注入的复杂对象（private field + setter property）--
        # TODO: subagent_orchestrator 改为 init() 中初始化或懒加载
        #   原因：依赖 agent_loop，需引入 Application.agent_loop property 后才能懒加载
        self._subagent_orchestrator:      SubAgentOrchestrator | None = None

        # -- 关闭信号（与 main.py 的 App 共享） --
        self._shutdown_event:             object | None = None  # asyncio.Event

        _app = self

    def init(self) -> None:
        """构造后立刻调用，初始化所有无复杂依赖的子系统。

        依赖：RuntimeContext 已 set（由 __main__.py 保证）。
        本方法在 _app = self 之后调用，因此 Application.current() 可用。
        """
        # 1. Sandbox — 纯构造，只依赖 RuntimeContext
        from system.sandbox import Sandbox
        self._sandbox = Sandbox(self.runtime_context)

        # 2. AgentspaceService — 依赖共享 Sandbox；异步 watcher 在 main.py 启动。
        from system.agentspace import AgentspaceService
        self._agentspace_service = AgentspaceService(
            self._sandbox,
            self.runtime_context.agentspace,
        )

        # 3. LLMProfileStore — 必须先于审批 Profile 和任何 Loop 恢复。
        from system.llm_profile_store import LLMProfileStore
        self._llm_profile_store = LLMProfileStore(
            self.runtime_context.agentspace,
            self._profile_lock,
        )

        # 3. CronRouter — 构造后从磁盘恢复持久化任务
        #    _load_all_tasks 内部调用 _get_cr() → Application.current().cron_router，
        #    此时 self._cron_router 已设好，不会重入问题。
        from component.cron_router import CronRouter
        self._cron_router = CronRouter()
        from component.extools.cron_tools import _load_all_tasks
        _load_all_tasks()

        # 4. SessionManager — 纯构造，只需 sessions 目录路径
        from gateway.session_manager import SessionManager
        from entity.constant import SESSIONS_DIR_NAME
        self._session_manager = SessionManager(
            str(self.runtime_context.workspace / SESSIONS_DIR_NAME)
        )

        # 4.5 动态端点恢复 — 依赖 SessionManager.exists 会话存在性检查，故放在其后
        from component.extools.dynamic_endpoint_tools import _load_all_endpoints
        _load_all_endpoints()

        # 5. FrontendSink — 纯构造，无依赖
        from entry.agent_sink import FrontendSink
        self._frontend_sink = FrontendSink()

        # 6. ApprovalBackendManager — 通过项目级审批 Profile 连接外部管理模型。
        self._approval_backend_manager = ApprovalBackendManager(
            self.runtime_context,
            self._llm_profile_store,
        )

        logger.info("Application initialized | subsystems ready")

    # ── 只读 property（init() 创建，外部不可赋值）──────────────

    @property
    def profile_lock(self) -> threading.RLock:
        """返回 Profile 根对象与会话选择共用的进程锁。"""
        return self._profile_lock

    @property
    def llm_profile_store(self) -> LLMProfileStore:
        """返回进程内唯一的 LLM Profile 根对象存储。"""
        return self._llm_profile_store  # type: ignore[return-value]

    @property
    def sandbox(self) -> Sandbox:
        return self._sandbox  # type: ignore[return-value]

    @property
    def agentspace_service(self) -> AgentspaceService:
        """返回 Agentspace 编辑器唯一业务服务。"""
        return self._agentspace_service  # type: ignore[return-value]

    @property
    def cron_router(self) -> CronRouter:
        return self._cron_router  # type: ignore[return-value]

    @property
    def session_manager(self) -> SessionManager:
        return self._session_manager  # type: ignore[return-value]

    @property
    def frontend_sink(self) -> FrontendSink:
        return self._frontend_sink  # type: ignore[return-value]

    @property
    def approval_backend_manager(self) -> ApprovalBackendManager:
        return self._approval_backend_manager  # type: ignore[return-value]

    @property
    def tool_registry(self) -> ToolRegistry:
        """全局工具注册表。"""
        from abstract.tools.registry import registry
        return registry

    # ── setter property（外部注入的复杂对象）──────────────────

    @property
    def subagent_orchestrator(self) -> SubAgentOrchestrator | None:
        return self._subagent_orchestrator

    @subagent_orchestrator.setter
    def subagent_orchestrator(self, value: SubAgentOrchestrator | None) -> None:
        self._subagent_orchestrator = value

    # ── 单例访问 ──────────────────────────────────────────────

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
        failures: list[str] = []
        # 1. 停止 Agentspace watcher 与 SSE 订阅。
        if self._agentspace_service is not None:
            try:
                await self._agentspace_service.shutdown()
            except Exception as exc:
                logger.exception("AgentspaceService shutdown failed: %s", exc)
                failures.append(f"AgentspaceService: {exc}")
        # 2. 停止 cron 后台任务
        if self._cron_router is not None:
            try:
                await self._cron_router.shutdown()
            except Exception as exc:
                logger.exception("CronRouter shutdown failed: %s", exc)
                failures.append(f"CronRouter: {exc}")
        # 2. 停止审批后端
        if self._approval_backend_manager is not None:
            try:
                await self._approval_backend_manager.shutdown()
            except Exception as exc:
                logger.exception("ApprovalBackendManager shutdown failed: %s", exc)
                failures.append(f"ApprovalBackendManager: {exc}")
        # 3. 停止子 Agent 编排器
        if self._subagent_orchestrator is not None:
            try:
                await self._subagent_orchestrator.shutdown_all()
            except Exception as exc:
                logger.exception("SubAgentOrchestrator shutdown failed: %s", exc)
                failures.append(f"SubAgentOrchestrator: {exc}")
        if failures:
            logger.error("Application shutdown completed with failures: %s", "; ".join(failures))
        else:
            logger.info("Application shutdown complete")


class ApprovalBackendManager:
    """管理由项目级审批 Profile 驱动的后端与客户端缓存。"""

    def __init__(
        self,
        ctx: RuntimeContext,
        llm_profile_store: LLMProfileStore,
    ) -> None:
        from component.approval.backend import ProfileApprovalBackend

        self._llm_profile_store = llm_profile_store
        self._backend: ApprovalBackend = ProfileApprovalBackend(
            ctx,
            llm_profile_store,
        )

    def get_backend(self) -> ApprovalBackend | None:
        """返回可用审批后端；未配置或配置无效时返回 ``None``。"""
        return self._backend if self._backend.is_available() else None

    def get_state(self) -> ApprovalProfileState:
        """返回项目级审批 Profile 的权威状态。"""
        from entity.puretype import ApprovalProfileState

        profile = self._llm_profile_store.get_approval_profile()
        if profile is None:
            return ApprovalProfileState()
        return ApprovalProfileState(
            profile_name=profile.name,
            model=profile.model or None,
            available=self._backend.is_available(),
        )

    def invalidate(self) -> None:
        """清除审批客户端缓存，使下一次调用按当前 Profile 重建。"""
        invalidate = getattr(self._backend, "invalidate", None)
        if callable(invalidate):
            invalidate()

    async def shutdown(self) -> None:
        """释放审批客户端引用。"""
        self.invalidate()