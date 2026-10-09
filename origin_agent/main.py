"""应用生命周期 — agent 进程的唯一异步入口点。

App 只负责：创建唯一 Application、平台信号处理、等待关闭请求、
调用 Application.start/shutdown、把关闭结果映射为既有退出码。
所有子系统装配、Gateway 启动与资源释放由 Application 协调。
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import TYPE_CHECKING

from system.application import Application

if TYPE_CHECKING:
    from system.context import RuntimeContext

from entity.constant import EXIT_FAILURE, EXIT_NORMAL, ShutdownReason

logger = logging.getLogger(__name__)


class App:
    """轻量异步运行器。由 __main__.py 使用 RuntimeContext 创建，
    然后 ``await app.run()`` 阻塞直到关闭并返回退出码。
    """

    def __init__(self, ctx: RuntimeContext) -> None:
        self._ctx: RuntimeContext = ctx
        self._application: Application | None = None
        self._wake_task: asyncio.Task[None] | None = None

    async def run(self) -> int:
        """阻塞直到关闭完成；失败关闭返回 1，绝不返回进化成功。"""
        logger.info(
            "App starting | mode=%s workspace=%s agentspace=%s fork=%s",
            self._ctx.mode,
            self._ctx.workspace,
            self._ctx.agentspace,
            self._ctx.fork_path,
        )

        self._application = Application(self._ctx)
        application = self._application

        try:
            await application.start()
        except Exception as exc:
            # 端口占用是启动前的明确业务拒绝：按普通停止退出，不进入 fallback。
            from gateway.system import GatewayPortBusyError
            if _contains_port_busy(exc):
                logger.error("Gateway port unavailable — normal stop: %s", exc)
                return EXIT_NORMAL
            logger.critical("Application startup failed: %s", exc, exc_info=True)
            return EXIT_FAILURE

        from system.runtime import RuntimeSystem
        runtime = application.get_system(RuntimeSystem)

        # ---- 信号处理（与 RuntimeSystem 共享同一关闭请求通道）----
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(
                    sig, runtime.request_shutdown, ShutdownReason.NORMAL,
                )
            except NotImplementedError:
                # Windows：add_signal_handler 不支持 — 使用 signal.signal
                try:
                    signal.signal(
                        sig,
                        lambda signum, frame: runtime.request_shutdown(ShutdownReason.NORMAL),
                    )
                except (ValueError, OSError):
                    logger.warning(
                        "Cannot register signal handler for %s on this platform", sig
                    )

        self._wake_task = asyncio.create_task(
            runtime.shutdown_event.wait(), name="app-shutdown-wait",
        )
        await self._wake_task

        # ---- 统一关闭（业务停止 + History 提交 + 逆拓扑注销）----
        shutdown_failed = False
        try:
            await application.shutdown()
        except BaseException as exc:
            shutdown_failed = True
            logger.critical("Application shutdown failed: %s", exc, exc_info=True)

        if shutdown_failed or runtime.exit_code == EXIT_FAILURE:
            return EXIT_FAILURE
        return runtime.exit_code

    def disarm_watchdog(self) -> None:
        """仅由 __main__ 在 asyncio.run 及线程池清理完成后调用。"""
        if self._application is None:
            return
        self._application.disarm_shutdown_deadline()


def _contains_port_busy(error: BaseException) -> bool:
    from gateway.system import GatewayPortBusyError
    if isinstance(error, GatewayPortBusyError):
        return True
    return isinstance(error, BaseExceptionGroup) and any(
        _contains_port_busy(member) for member in error.exceptions
    )
