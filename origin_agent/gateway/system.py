"""GatewaySystem：FastAPI/uvicorn/socket 与全部路由后台工作的唯一所有者。"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
import errno
import logging
import socket
from typing import Any, TypeVar

import uvicorn
from fastapi import FastAPI
from framework import AsyncSystem

from abstract.tools.discover import ToolDiscoverySystem
from component.approval.system import ApprovalSystem
from component.cron_router import CronRouter
from component.dynamic_endpoints import DynamicEndpointSystem
from entity.constant import (
    GATEWAY_SHUTDOWN_TIMEOUT_SECONDS,
    GATEWAY_START_TIMEOUT_SECONDS,
    SYSTEM_QUIESCE_TIMEOUT_SECONDS,
)
from entry.agent_sink import FrontendSink
from gateway.lifecycle import GatewayAdmission, GatewayReadyTracker
from gateway.session_manager import SessionManager
from subagent.orchestrator import SubAgentOrchestrator
from system.agentspace.service import AgentspaceService
from system.lifecycle import LifecycleFailure, TaskOwner, close_resources
from system.llm_profile_store import LLMProfileStore
from system.runtime import RuntimeSystem
from system.sandbox import Sandbox
from system.session_metadata import SessionMetadataService
from system.shell_manager import ShellManager

logger = logging.getLogger(__name__)

WorkResultT = TypeVar("WorkResultT")


class GatewayPortBusyError(RuntimeError):
    """启动前端口已被占用的明确业务拒绝；调用方按普通停止处理。"""


def check_port_available(host: str, port: int) -> bool:
    """启动前探测端口是否空闲；bind 竞态仍由 GatewaySystem 处理为启动失败。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
            return True
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE:
                return False
            raise


class _GatewayUvicornServer(uvicorn.Server):
    """禁用自身信号处理并在真实 startup 完成后报告就绪。"""

    def __init__(self, config: uvicorn.Config, ready: GatewayReadyTracker) -> None:
        super().__init__(config)
        self._ready_tracker = ready

    def install_signal_handlers(self) -> None:
        # 进程信号统一由 App 层处理。
        return

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets)
        self._ready_tracker.mark_ready()


class GatewaySystem(AsyncSystem):
    """最后唤醒、首先注销；History 刷新完成前只封闭输入不关闭输出。"""

    def __init__(self) -> None:
        super().__init__(dependencies=(
            RuntimeSystem, ToolDiscoverySystem, SessionManager, SubAgentOrchestrator,
            DynamicEndpointSystem, FrontendSink, AgentspaceService, ApprovalSystem,
            LLMProfileStore, SessionMetadataService, CronRouter, ShellManager, Sandbox,
        ))
        self._runtime: RuntimeSystem | None = None
        self._admission: GatewayAdmission | None = None
        self._ready = GatewayReadyTracker()
        self._owner: TaskOwner | None = None
        self._app: FastAPI | None = None
        self._server: _GatewayUvicornServer | None = None
        self._serve_task: asyncio.Task[None] | None = None
        self._socket: socket.socket | None = None

    # -- 唤醒期入口（P22 装配前由 virtual_awake 使用）--

    @property
    def fastapi_app(self) -> FastAPI:
        if self._app is None:
            raise LifecycleFailure("GatewaySystem has not built its FastAPI application")
        return self._app

    @property
    def admission(self) -> GatewayAdmission:
        if self._admission is None:
            raise LifecycleFailure("GatewaySystem has not been awakened")
        return self._admission

    @property
    def ready_tracker(self) -> GatewayReadyTracker:
        return self._ready

    @property
    def task_owner(self) -> TaskOwner:
        if self._owner is None:
            raise LifecycleFailure("GatewaySystem has not been awakened")
        return self._owner

    def spawn_work(self, coro: Coroutine[Any, Any, WorkResultT], *, name: str) -> asyncio.Task[WorkResultT]:
        """登记路由启动的后台任务；输入登记必须在创建本任务之前完成。"""
        return self.task_owner.create(coro, name=name)

    async def virtual_awake(self) -> None:
        self._runtime = self.get_system(RuntimeSystem)
        self._admission = GatewayAdmission(self._runtime)
        self._owner = TaskOwner("gateway", self._runtime.record_failure)
        await self._start()

    async def _start(self) -> None:
        from gateway.server import build_router_app

        runtime = self.runtime
        ctx = runtime.context
        if not check_port_available(ctx.gateway_host, ctx.gateway_port):
            raise GatewayPortBusyError(
                f"Gateway port {ctx.gateway_port} on {ctx.gateway_host} is already in use"
            )
        try:
            self._app = build_router_app()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((ctx.gateway_host, ctx.gateway_port))
                sock.listen(socket.SOMAXCONN)
                sock.setblocking(False)
                sock.set_inheritable(False)
            except BaseException:
                sock.close()
                raise
            self._socket = sock
            config = uvicorn.Config(
                app=self._app,
                log_level="warning",
                ws_max_size=100 * 1024 * 1024,  # 100MB — 容纳大视频 base64
            )
            self._server = _GatewayUvicornServer(config, self._ready)
            self._serve_task = asyncio.create_task(
                self._server.serve(sockets=[sock]), name="gateway-uvicorn-serve",
            )
            wait_ready = asyncio.create_task(self._ready.wait_ready(), name="gateway-ready-wait")
            try:
                done, _ = await asyncio.wait(
                    {wait_ready, self._serve_task},
                    timeout=GATEWAY_START_TIMEOUT_SECONDS,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                if not wait_ready.done():
                    wait_ready.cancel()
                    await asyncio.gather(wait_ready, return_exceptions=True)
            if self._serve_task in done:
                # serve 在 ready 前结束：启动失败，传播真实异常。
                self._serve_task.result()
                raise LifecycleFailure("Gateway server exited before becoming ready")
            if not self._ready.ready:
                raise LifecycleFailure(
                    f"Gateway did not finish startup within {GATEWAY_START_TIMEOUT_SECONDS}s"
                )
            logger.info(
                "Gateway listening on http://%s:%d (ws /ws/chat)",
                ctx.gateway_host, ctx.gateway_port,
            )
        except BaseException:
            await self._release_startup_resources()
            raise

    @property
    def runtime(self) -> RuntimeSystem:
        if self._runtime is None:
            raise LifecycleFailure("GatewaySystem has not been awakened")
        return self._runtime

    async def _release_startup_resources(self) -> None:
        """半初始化失败的资源回收；不恢复业务状态。"""
        async def stop_serve() -> None:
            server, task = self._server, self._serve_task
            self._server = None
            self._serve_task = None
            if task is None:
                return
            if server is not None:
                server.should_exit = True
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        async def close_socket() -> None:
            sock, self._socket = self._socket, None
            if sock is not None:
                await asyncio.to_thread(sock.close)

        async def close_owner() -> None:
            if self._owner is not None and not self._owner.is_idle:
                await self._owner.cancel_and_wait(timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS)

        await close_resources((stop_serve, close_socket, close_owner))

    # -- P3 关闭阶段接口 --

    def stop_accepting(self) -> None:
        """封闭新业务与 WS 输入；既有输出连接保留到 History 刷新完成。"""
        self.admission.stop_accepting()

    async def cancel_background_work(self) -> None:
        """取消自动标题、恢复、路由后台工作；连接与发送任务不受影响。"""
        await self.task_owner.cancel_and_wait(timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS)

    async def stop_server(self) -> None:
        """结束 SSE/WS、uvicorn 与套接字；任务终局必须确认，失败上抛。"""
        server = self._server
        serve_task = self._serve_task
        self._server = None
        self._serve_task = None

        async def stop_serve() -> None:
            if serve_task is None:
                return
            if server is not None:
                server.should_exit = True
            done, _ = await asyncio.wait(
                {serve_task}, timeout=GATEWAY_SHUTDOWN_TIMEOUT_SECONDS,
            )
            if not done:
                serve_task.cancel()
                try:
                    await serve_task
                except asyncio.CancelledError as exc:
                    raise LifecycleFailure(
                        "Gateway server task did not finish after cancellation"
                    ) from exc
            else:
                serve_task.result()

        async def close_socket() -> None:
            sock, self._socket = self._socket, None
            if sock is not None:
                await asyncio.to_thread(sock.close)

        await close_resources((stop_serve, close_socket))

    async def virtual_shotdown(self) -> None:
        self.stop_accepting()
        await self.stop_server()
