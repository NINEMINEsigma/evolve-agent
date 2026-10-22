"""浏览器连接与应用自有无头进程的唯一生命周期所有者。"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
import subprocess
from typing import TYPE_CHECKING

from framework import AsyncSystem

from entity.constant import (
    BROWSER_PROCESS_EXIT_TIMEOUT_SECONDS,
    CDP_ENDPOINT_DEFAULT,
    CONNECT_TIMEOUT_MS,
    SYSTEM_QUIESCE_TIMEOUT_SECONDS,
)
from system.lifecycle import (
    ApplicationStoppingError, LifecycleFailure, TaskOwner, close_resources,
)
from interface.browser_system import IBrowserSystem
from interface.runtime_system import IRuntimeSystem
from system.cleanup_errors import ResourceCleanupPendingError
from system.process_termination import OwnedProcessIdentity, terminate_owned_tree
from entity.puretype.browser import HeadlessCleanupResult
from entity.puretype.resource_cleanup import CleanupReport

if TYPE_CHECKING:
    from playwright.async_api import Browser, Playwright


class BrowserSystem(IBrowserSystem):
    """仅关闭 CDP 客户端连接；只终止明确登记为应用自有的无头进程。"""

    def __init__(self) -> None:
        super().__init__(dependencies=(IRuntimeSystem,))
        self._runtime: IRuntimeSystem | None = None
        self._owner: TaskOwner | None = None
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._endpoint = CDP_ENDPOINT_DEFAULT
        self._connection_lock = asyncio.Lock()
        self._closed = False
        # 多次启动不能覆盖尚未释放的旧句柄；每个进程只登记一次。
        self._headless_procs: dict[int, subprocess.Popen] = {}
        self._process_cleanup: dict[int, asyncio.Task[int]] = {}
        self._cleanup_failures: list[BaseException] = []
        self._teardown_task: asyncio.Task[None] | None = None

    async def virtual_awake(self) -> None:
        self._runtime = self.get_system(IRuntimeSystem)
        self._owner = TaskOwner("browser-requests", self.runtime.record_failure)

    @property
    def runtime(self) -> IRuntimeSystem:
        if self._runtime is None:
            raise LifecycleFailure("BrowserSystem has not been awakened")
        return self._runtime

    @property
    def task_owner(self) -> TaskOwner:
        if self._owner is None:
            raise LifecycleFailure("BrowserSystem has not been awakened")
        return self._owner

    @contextmanager
    def _admit(self) -> Iterator[None]:
        with self.runtime.admission():
            if self._closed:
                raise ApplicationStoppingError("Browser operations have closed")
            yield

    def current_endpoint(self) -> str:
        return self._endpoint

    async def get_browser(self, endpoint: str = CDP_ENDPOINT_DEFAULT) -> Browser:
        return await self.task_owner.run_request(
            lambda: self._get_browser(endpoint),
            name="browser-connect",
            admission=self._admit,
        )

    async def _get_browser(self, endpoint: str) -> Browser:
        async with self._connection_lock:
            with self._admit():
                pass
            if self._browser is not None and self._browser.is_connected():
                return self._browser
            await self._teardown_locked()
            # 可选依赖只在明确连接时加载，System 唤醒不会启动浏览器。
            from playwright.async_api import async_playwright
            manager = async_playwright()
            try:
                self._pw = await manager.start()
                with self._admit():
                    pass
                self._browser = await self._pw.chromium.connect_over_cdp(
                    endpoint, timeout=CONNECT_TIMEOUT_MS,
                )
                self._endpoint = endpoint
                return self._browser
            except BaseException as error:
                try:
                    if self._pw is not None:
                        await self._teardown_locked()
                    else:
                        # manager 已开始取得驱动资源但尚未返回 Playwright 时也释放。
                        await manager.__aexit__(type(error), error, error.__traceback__)
                except BaseException as cleanup_error:
                    failure = LifecycleFailure("Browser connection cleanup failed")
                    failure.__cause__ = cleanup_error
                    self.runtime.record_failure(failure)
                    raise BaseExceptionGroup("Browser connection failed", [error, failure])
                raise

    def _report_cleanup(self, task: asyncio.Task) -> None:
        if task.cancelled():
            error: BaseException | None = LifecycleFailure("Browser resource cleanup was cancelled")
        else:
            error = task.exception()
        if error is not None:
            self._cleanup_failures.append(error)
            self.runtime.record_failure(error)

    async def _wait_cleanup(self, task: asyncio.Task) -> None:
        done, _ = await asyncio.wait({task}, timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS)
        if not done:
            failure = LifecycleFailure("Browser resource cleanup exceeded its deadline")
            self.runtime.record_failure(failure)
            raise failure
        task.result()

    async def teardown(self) -> CleanupReport:
        """Disconnect the owned browser connection without killing a user browser."""
        if self._browser is None and self._pw is None:
            return CleanupReport(complete=True)
        browser = self._browser
        driver = self._pw
        reservation = self.runtime.cleanup.open_producer(
            owner="BrowserSystem",
            loop=asyncio.get_running_loop(),
        ).reserve()

        async def release() -> None:
            if browser is not None:
                await browser.close()
            if driver is not None:
                await driver.stop()

        handle = self.runtime.cleanup.begin(
            reservation,
            resource_id=f"browser:{id(browser)}:{id(driver)}",
            phase="disconnect",
            factory=release,
            is_released=lambda: browser is None or not browser.is_connected(),
            kill_authorized=False,
        )
        handle.retain((browser, driver))
        self._browser = None
        self._pw = None
        return await handle.wait(timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS)

    async def _teardown(self) -> None:
        async with self._connection_lock:
            await self._teardown_locked()

    async def _teardown_locked(self) -> None:
        async def disconnect() -> None:
            if self._browser is not None:
                # connect_over_cdp 返回附加连接；close 断开该连接，不杀用户进程。
                await self._browser.close()
                self._browser = None

        async def stop_driver() -> None:
            if self._pw is not None:
                await self._pw.stop()
                self._pw = None

        try:
            await close_resources((disconnect, stop_driver))
        except BaseException as error:
            failure = LifecycleFailure("Browser CDP or Playwright release failed")
            failure.__cause__ = error
            raise failure

    def register_headless_proc(self, proc: subprocess.Popen) -> None:
        """取得已创建进程的所有权；即使停止刚发生也必须收回该句柄。"""
        if asyncio.get_running_loop() is not self.runtime.loop:
            raise LifecycleFailure("Browser process registration requires the runtime loop")
        existing = self._headless_procs.get(proc.pid)
        if existing is not None and existing is not proc:
            raise LifecycleFailure("Browser process identifier already belongs to another handle")
        self._headless_procs[proc.pid] = proc

    async def cleanup_headless_browser(self) -> HeadlessCleanupResult:
        killed = 0
        pending: list[str] = []
        for proc in tuple(self._headless_procs.values()):
            identity = OwnedProcessIdentity.from_popen(proc)
            if identity is None or not identity.still_matches():
                pending.append(str(proc.pid))
                continue
            if proc.poll() is None:
                await terminate_owned_tree(identity)
            if proc.poll() is not None:
                killed += 1
                self._headless_procs.pop(proc.pid, None)
            else:
                pending.append(str(proc.pid))
        return HeadlessCleanupResult(
            killed=killed,
            cleanup=CleanupReport(complete=not pending, pending_resources=pending),
        )

    def close_admission(self) -> None:
        self._closed = True

    async def virtual_shotdown(self) -> None:
        self.close_admission()
        async def stop_requests() -> None:
            await self.task_owner.cancel_and_wait(timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS)

        async def release_connections() -> None:
            if not self.task_owner.is_idle:
                raise LifecycleFailure("Cannot release browser resources while requests are active")
            await self.teardown()

        async def release_processes() -> None:
            await self.cleanup_headless_browser()

        await close_resources((stop_requests, release_connections, release_processes))
        if self._cleanup_failures:
            raise BaseExceptionGroup("Browser cleanup failed", list(self._cleanup_failures))
