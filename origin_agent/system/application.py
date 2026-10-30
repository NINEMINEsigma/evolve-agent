"""进程级唯一异步架构；业务 System 由 framework 注册表持有。"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from contextlib import ExitStack
from graphlib import CycleError, TopologicalSorter
import logging
from typing import TYPE_CHECKING, ClassVar, Never

from framework import AsyncArchitecture, AsyncSystem

from entity.constant import ApplicationState, ShutdownReason
from entity.error import LifecycleFailure
from system.lifecycle import close_resources

if TYPE_CHECKING:
    from interface.runtime_system import IDPRuntimeSystem, IRuntimeSystem
    from system.context import RuntimeContext

logger = logging.getLogger(__name__)


def _is_port_busy_rejection(error: BaseException) -> bool:
    from entity.error import GatewayPortBusyError
    if isinstance(error, GatewayPortBusyError):
        return True
    return isinstance(error, BaseExceptionGroup) and all(
        _is_port_busy_rejection(member) for member in error.exceptions
    )


def _build_system_manifest(
    context: RuntimeContext,
) -> list[tuple[type[AsyncSystem], AsyncSystem]]:
    """Build the ordered interface-slot and implementation pairs without side effects."""
    from abstract.mcp.system import MCPSystem
    from abstract.tools.discover import ToolDiscoverySystem
    from abstract.tools.registry import ToolRegistry
    from component.approval.system import ApprovalSystem
    from buildin_tools.browser.system import BrowserSystem
    from component.cron_router import CronRouter
    from component.dynamic_endpoints import DynamicEndpointSystem
    from entry.agent_sink import FrontendSink
    from gateway.session_manager import SessionManager
    from gateway.system import GatewaySystem
    from interface.approval_system import IApprovalSystem
    from interface.agentspace_service import IAgentspaceService
    from interface.browser_system import IBrowserSystem
    from interface.cron_router import ICronRouter
    from interface.dynamic_endpoint_system import IDynamicEndpointSystem
    from interface.frontend_sink import IFrontendSink
    from interface.gateway_system import IGatewaySystem
    from interface.llm_profile_store import ILLMProfileStore
    from interface.logger_system import ILoggerSystem
    from interface.lsp_manager import ILSPManager
    from interface.mcp_system import IMCPSystem
    from interface.modality_capability_system import IModalityCapabilitySystem
    from interface.runtime_system import IRuntimeSystem
    from interface.sandbox import ISandbox
    from interface.session_manager import ISessionManager
    from interface.session_metadata_service import ISessionMetadataService
    from interface.shell_manager import IShellManager
    from interface.subagent_orchestrator import ISubAgentOrchestrator
    from interface.subprocess_runner import ISubprocessRunner
    from interface.tool_discovery_system import IToolDiscoverySystem
    from interface.tool_registry import IToolRegistry
    from subagent.orchestrator import SubAgentOrchestrator
    from system.agentspace.service import AgentspaceService
    from system.llm_profile_store import LLMProfileStore
    from system.logger import LoggerSystem
    from system.lsp import LSPManager
    from system.modality_capability import ModalityCapabilitySystem
    from system.runtime import RuntimeSystem
    from system.sandbox import Sandbox
    from system.session_metadata import SessionMetadataService
    from system.shell_manager import ShellManager
    from system.subprocess_utils import SubprocessRunner

    return [
        (IRuntimeSystem, RuntimeSystem(context)),
        (ILoggerSystem, LoggerSystem()),
        (ISubprocessRunner, SubprocessRunner()),
        (ISandbox, Sandbox()),
        (IShellManager, ShellManager()),
        (IAgentspaceService, AgentspaceService()),
        (ILLMProfileStore, LLMProfileStore()),
        (ISessionMetadataService, SessionMetadataService()),
        (IApprovalSystem, ApprovalSystem()),
        (IFrontendSink, FrontendSink()),
        (IToolRegistry, ToolRegistry()),
        (ILSPManager, LSPManager()),
        (IBrowserSystem, BrowserSystem()),
        (IModalityCapabilitySystem, ModalityCapabilitySystem()),
        (ICronRouter, CronRouter()),
        (ISessionManager, SessionManager()),
        (ISubAgentOrchestrator, SubAgentOrchestrator()),
        (IDynamicEndpointSystem, DynamicEndpointSystem()),
        (IMCPSystem, MCPSystem()),
        (IToolDiscoverySystem, ToolDiscoverySystem()),
        (IGatewaySystem, GatewaySystem()),
    ]


class Application(AsyncArchitecture):
    """一次进程只装配一个架构；失败或关闭后不能重新创建。"""

    _current: ClassVar[Application | None] = None

    def __init__(self, runtime_context: RuntimeContext) -> None:
        if Application._current is not None:
            raise LifecycleFailure("Application has already been created in this process")
        super().__init__()
        self._startup_context = runtime_context
        self._state = ApplicationState.NEW
        self._shutdown_task: asyncio.Task[None] | None = None
        self._shutdown_failures: list[BaseException] = []
        Application._current = self

    @classmethod
    def current(cls) -> Application:
        app = Application._current
        if app is None:
            raise RuntimeError("Application has not been created")
        if app._state in (ApplicationState.CLOSED, ApplicationState.FAILED):
            raise LifecycleFailure("Application lifecycle has ended")
        return app

    @staticmethod
    def get() -> Application:
        """覆盖 framework 的默认工厂，避免创建第二个基础架构。"""
        return Application.current()

    def _validate_system_graph(
        self,
        systems: Sequence[tuple[type[AsyncSystem], AsyncSystem]],
    ) -> tuple[type[AsyncSystem], ...]:
        """Validate the interface-slot dependency graph independently of manifest order."""
        system_types = tuple(system_type for system_type, _ in systems)
        if len(set(system_types)) != len(system_types):
            raise LifecycleFailure("Application contains duplicate System slots")
        known = set(system_types)
        graph: dict[type[AsyncSystem], frozenset[type[AsyncSystem]]] = {}
        for system_type, system in systems:
            if not isinstance(system, system_type):
                raise LifecycleFailure(
                    f"System implementation {type(system).__name__} does not implement "
                    f"slot {system_type.__name__}"
                )
            missing = system.dependencies - known
            if missing:
                names = ", ".join(sorted(dependency.__name__ for dependency in missing))
                raise LifecycleFailure(
                    f"System slot {system_type.__name__} has missing dependencies: {names}"
                )
            graph[system_type] = system.dependencies
        try:
            TopologicalSorter(graph).prepare()
        except CycleError as exc:
            raise LifecycleFailure("Application System dependency graph contains a cycle") from exc
        return system_types

    # -- 装配与关闭（P22）--

    async def start(self, *, shutdown_callbacks: ExitStack) -> None:
        """串行注册并开放输入；将硬截止解除回调交给 asyncio.run 外层。"""
        if self._state is not ApplicationState.NEW:
            raise LifecycleFailure(f"Application cannot start from state {self._state}")
        self._state = ApplicationState.STARTING
        systems = _build_system_manifest(self._startup_context)
        order = self._validate_system_graph(systems)
        from interface.cron_router import ICronRouter
        from interface.runtime_system import IDPRuntimeSystem, IRuntimeSystem
        try:
            for system_type, system in systems:
                # NOTE: 逻辑上不应该重复注册, 重复的也不会以返回值false完成调用
                await self.register(system, system_type=system_type)
            runtime = self.get_system(IRuntimeSystem)
            runtime.mark_running()
            AsyncArchitecture.get_system(self, ICronRouter).activate()
        except BaseException as startup_error:
            self._state = ApplicationState.FAILED
            # 注册失败时允许取得尚未完成唤醒的实例；Runtime尚未注册则不使用它。
            runtime = self.has_system(IRuntimeSystem)
            if runtime is not None:
                shutdown_callbacks.callback(runtime.disarm_shutdown_deadline)
            failed_awake_systems = tuple(
                instance for slot, instance in systems
                if isinstance(instance, IDPRuntimeSystem)
                and self.has_system(slot) is instance
                and instance.system_slot is not None
                and not instance.is_awake
            )
            await self._cleanup_startup_failure(
                startup_error, runtime, failed_awake_systems=failed_awake_systems,
            )
            raise
        shutdown_callbacks.callback(runtime.disarm_shutdown_deadline)
        self._state = ApplicationState.RUNNING
        logger.info("Application started | systems=%d", len(order))

    async def _cleanup_startup_failure(
        self, error: BaseException, runtime: IRuntimeSystem | None,
        *, failed_awake_systems: Sequence[IDPRuntimeSystem],
    ) -> None:
        ordinary_rejection = _is_port_busy_rejection(error)
        if runtime is not None:
            if ordinary_rejection:
                runtime.request_shutdown(ShutdownReason.NORMAL)
            else:
                runtime.record_failure(error)
        try:
            await self._unregister_systems(failed_awake_systems=failed_awake_systems)
        except BaseException as cleanup_error:
            combined = BaseExceptionGroup("Application startup and cleanup failed", [error, cleanup_error])
            # 根级联或最终清理失败时，保留启动错误和清理错误并一同传播。
            raise LifecycleFailure("Application startup cleanup failed") from combined
        if not ordinary_rejection:
            # 统一为失败启动；原组保留为cause，避免混合端口异常被外层any匹配误报退出0。
            raise LifecycleFailure("Application startup failed") from error

    async def _hold_failed_shutdown(
        self, error: BaseException, runtime: IRuntimeSystem | None,
    ) -> Never:
        self._shutdown_failures.append(error)
        if runtime is None:
            raise error
        runtime.record_failure(error)
        runtime.request_shutdown(ShutdownReason.FAILURE)
        # 保留尚在使用的依赖和主loop，硬截止由独立daemon Timer执行。
        await asyncio.get_running_loop().create_future()
        raise LifecycleFailure("Failed shutdown hold unexpectedly completed")

    async def _prepare_system_shutdown(self) -> None:
        """Quiesce real tool work before preparing resource owners in dependency order."""
        from interface.runtime_system import IDPRuntimeSystem
        from interface.tool_registry import IToolRegistry

        systems = tuple(self._get_system_stack())
        for system in systems:
            if isinstance(system, IToolRegistry):
                system.close_dispatch()
                await system.cancel_pending_calls()
                await system.wait_idle()
        for system in reversed(systems):
            if isinstance(system, IDPRuntimeSystem):
                await system.prepare_shutdown()

    async def _unregister_systems(
        self, *, failed_awake_systems: Sequence[IDPRuntimeSystem] = (),
    ) -> None:
        """Prepare while bound, cascade from Logger, then drain resource cleanup."""
        from interface.logger_system import ILoggerSystem
        from interface.runtime_system import IRuntimeSystem

        # 启动失败可能没有Runtime或只有未唤醒实例；正常路径通过get_system获取。
        runtime = self.has_system(IRuntimeSystem)
        if runtime is not None and runtime.is_awake:
            runtime = self.get_system(IRuntimeSystem)
        # NOTE: 根级联会移除Runtime，后续资源清理只使用这个局部引用，不再输出日志。
        if runtime is not None and runtime.shutdown_reason is None:
            runtime.request_shutdown(ShutdownReason.NORMAL)
        try:
            for system in failed_awake_systems:
                await system.prepare_failed_startup()
            await self._prepare_system_shutdown()
        except BaseException as error:
            await self._hold_failed_shutdown(error, runtime)
        await self.shoudown_system(ILoggerSystem)
        failures: list[BaseException] = []
        if runtime is not None:
            runtime.cleanup.close_producers()
            try:
                await runtime.cleanup.drain()
            except BaseException as error:
                failures.append(error)
        if failures:
            raise BaseExceptionGroup("Application system unregistration failed", failures)

    async def _stop_business(self) -> None:
        """P3 步骤 2—7：冻结输入、停止生成、提交 History、保留输出到最后。"""
        from interface.approval_system import IApprovalSystem
        from interface.cron_router import ICronRouter
        from interface.frontend_sink import IFrontendSink
        from interface.gateway_system import IGatewaySystem
        from interface.llm_profile_store import ILLMProfileStore
        from interface.mcp_system import IMCPSystem
        from interface.modality_capability_system import IModalityCapabilitySystem
        from interface.session_manager import ISessionManager
        from interface.session_metadata_service import ISessionMetadataService
        from interface.subagent_orchestrator import ISubAgentOrchestrator
        from interface.subprocess_runner import ISubprocessRunner
        from interface.tool_registry import IToolRegistry

        gateway = AsyncArchitecture.get_system(self, IGatewaySystem)
        sessions = AsyncArchitecture.get_system(self, ISessionManager)
        orchestrator = AsyncArchitecture.get_system(self, ISubAgentOrchestrator)
        cron = AsyncArchitecture.get_system(self, ICronRouter)
        sink = AsyncArchitecture.get_system(self, IFrontendSink)
        registry = AsyncArchitecture.get_system(self, IToolRegistry)
        mcp = AsyncArchitecture.get_system(self, IMCPSystem)
        subprocesses = AsyncArchitecture.get_system(self, ISubprocessRunner)
        metadata = AsyncArchitecture.get_system(self, ISessionMetadataService)
        approval = AsyncArchitecture.get_system(self, IApprovalSystem)
        modality = AsyncArchitecture.get_system(self, IModalityCapabilitySystem)

        # 步骤 2：同一接收状态下封闭新工作；长连接与输出保留。
        gateway.stop_accepting()
        sessions.freeze_inputs()
        orchestrator.freeze_inputs()
        cron.freeze()
        sink.close_admission()
        mcp.close_admission()

        # 步骤 3—4：停止生成请求与在途调用；取消路由后台工作。
        async def stop_rounds() -> None:
            await sessions.stop_rounds()
            await orchestrator.stop_rounds()

        async def cancel_pending() -> None:
            await close_resources((
                registry.cancel_pending_calls,
                mcp.stop_calls,
                subprocesses.terminate_all,
                metadata.cancel_pending,
                approval.cancel_pending,
                modality.cancel_pending,
                gateway.cancel_background_work,
            ))
            sink.cancel_pending_interactions()

        await close_resources((stop_rounds, cancel_pending))

        # 步骤 5—6：子会话未消费输入与反馈先交接，再串行提交主会话 History。
        await orchestrator.flush_inputs()
        await orchestrator.transfer_shutdown_feedback()
        report = await sessions.flush_inputs()
        logger.info(
            "Shutdown input flush | accepted=%d appended=%d persisted=%d ephemeral=%d",
            report.accepted, report.appended, report.persisted, report.ephemeral,
        )

        # 步骤 7：History 刷新完成后才结束连接与服务器。
        await sink.close_all_connections()
        await gateway.stop_server()

    async def shutdown(self) -> None:
        """单一协调任务：业务停止 → 从 Logger 根节点级联注销；重复请求等待同一任务。"""
        task = self._shutdown_task
        if task is None:
            task = asyncio.create_task(self._shutdown_impl(), name="application-shutdown")
            self._shutdown_task = task
        await asyncio.shield(task)

    async def _shutdown_impl(self) -> None:
        from interface.runtime_system import IRuntimeSystem
        runtime = self.get_system(IRuntimeSystem)
        self._state = ApplicationState.STOPPING
        failures: list[BaseException] = []
        try:
            await self._stop_business()
        except BaseException as exc:
            await self._hold_failed_shutdown(exc, runtime)
        try:
            await self._unregister_systems()
        except BaseException as exc:
            failures.append(exc)
        failures.extend(error for error in runtime.failures if not any(
            existing is error for existing in failures
        ))
        self._state = (
            ApplicationState.FAILED if failures else ApplicationState.CLOSED
        )
        if failures:
            raise BaseExceptionGroup("Application shutdown failed", failures)
