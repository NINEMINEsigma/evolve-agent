"""应用生命周期 — agent 进程的唯一异步入口点。

不在模块级别导入任何重型子系统。所有组件在 ``App.run()``
内部延迟加载，使导入错误能够干净地暴露。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import signal
from typing import TYPE_CHECKING

from system.application import Application

if TYPE_CHECKING:
    from system.context import RuntimeContext

from entity.constant import CUSTOM_MODELS_DIR, CUSTOM_TOOLS_DIR

logger = logging.getLogger(__name__)

# 模块级引用，指向运行中的 App 实例。
# 在 App.__init__ 中设置，在 shutdown 时清除。
# 进化子系统通过它请求以退出码 -1 进行受控关闭。
_app: App | None = None


def request_evolution() -> None:
    """标记运行中的 App 以退出码 -1 退出并立即触发关闭。

    由 ``evolve.code.finalize_evolution`` 在 fork 目录
    通过所有验证检查后调用。直接触发关闭事件，
    不需要等待 gateway 的 WebSocket 回调（后者在
    WebSocket 提前断开时无法可靠抵达）。
    """
    global _app
    if _app is not None:
        _app._exit_code = -1
        _app._shutdown_event.set()
        logger.info("Evolution triggered — exiting with code -1")


def trigger_evolution_shutdown() -> None:
    """如果已请求进化，触发实际关闭。

    由 gateway 在发送可能完成代码进化周期的响应后调用。
    如果退出码为 -1，设置关闭事件使 ``App.run()`` 返回，
    编排器（run.py）执行 slow→fast 交换。
    """
    global _app
    if _app is not None and _app._exit_code == -1:
        _app._shutdown_event.set()
        logger.info("Evolution shutdown triggered — exiting with code -1")


class App:
    """轻量异步运行器。由 __main__.py 使用 RuntimeContext 创建，
    然后 ``await app.run()`` 阻塞直到关闭。
    """

    def __init__(self, ctx: RuntimeContext) -> None:
        global _app
        self.ctx: RuntimeContext = ctx
        # 关闭信号事件，set 后 run() 返回
        self._shutdown_event: asyncio.Event = asyncio.Event()
        # 进程退出码，-1 表示需要进化交换
        self._exit_code: int = 0
        # uvicorn Server 实例
        self._gateway_server: object | None = None
        # gateway 后台 asyncio task
        self._gateway_task: asyncio.Task[None] | None = None
        _app = self

    async def run(self) -> int:
        """阻塞直到请求关闭。返回退出码。"""
        logger.info(
            "App starting | mode=%s workspace=%s agentspace=%s fork=%s",
            self.ctx.mode,
            self.ctx.workspace,
            self.ctx.agentspace,
            self.ctx.fork_path,
        )

        # ---- 启动 gateway ----
        await self._start_gateway()

        # ---- 信号处理 ----
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._request_shutdown)
            except NotImplementedError:
                # Windows：add_signal_handler 不支持 — 使用 signal.signal
                try:
                    signal.signal(sig, lambda signum, frame: self._request_shutdown())
                except (ValueError, OSError):
                    logger.warning(
                        "Cannot register signal handler for %s on this platform", sig
                    )

        await self._shutdown_event.wait()

        # ---- 停止 gateway ----
        await self._stop_gateway()

        # ---- 排空后台任务 ----
        await self._drain_background_tasks()

        # ---- 清理后台服务进程 ----
        try:
            from component.extools.background_service import cleanup_background_services
            killed = await asyncio.to_thread(cleanup_background_services)
            if killed:
                logger.info("Cleaned up %d background service(s)", killed)
        except Exception as exc:
            logger.warning("Background service cleanup failed: %s", exc)

        # ---- 关闭 Application 子系统 ----
        try:
            await Application.current().shutdown()
        except Exception as exc:
            logger.warning("Application shutdown failed: %s", exc)

        logger.info("App shutdown complete")
        return self._exit_code

    def _request_shutdown(self) -> None:
        logger.info("Shutdown requested")
        self._shutdown_event.set()

    # -- gateway 生命周期 --------------------------------------------------

    async def _start_gateway(self) -> None:
        """创建 uvicorn server 并作为后台 task 运行。"""
        try:
            from gateway.server import create_server, set_agent_loop, set_agentspace_path
            from dashboard.server import set_agent_loop as set_dashboard_agent_loop
        except ImportError as exc:
            logger.warning("Gateway unavailable (import error): %s", exc)
            self._shutdown_event.set()
            return

        # ---- 初始化 sandbox + 工具 ----
        try:
            from system.sandbox import Sandbox
            _sandbox: Sandbox = Sandbox(self.ctx)
            # 先注入 sandbox 到唯一入口（在 discover 之前完成）
            import component.tools.filesystem as _fs
            _fs.set_sandbox(_sandbox)
            # AST 自动发现并注册工具模块
            from abstract.tools.discover import discover_builtin_tools
            from system.pathutils import find_repo_root, get_agent_dir
            import sys
            _agent_root: Path = get_agent_dir()
            _root: Path = find_repo_root()
            if str(_root) not in sys.path:
                sys.path.insert(0, str(_root))
            discover_builtin_tools(str(_agent_root / "component" / "tools"), "component.tools")
            discover_builtin_tools(str(_agent_root / "component" / "extools"), "component.extools")
            discover_builtin_tools(str(_agent_root / "component" / "mutliagenttools"), "component.mutliagenttools")
            _custom_tools: Path = _root / CUSTOM_TOOLS_DIR
            if _custom_tools.exists():
                discover_builtin_tools(str(_custom_tools), CUSTOM_TOOLS_DIR)
            # 注册 MCP 工具（桥接 + 连接 server）
            import component.mcp_tools  # noqa: F401 — 安装 MCP 回调
            component.mcp_tools.init_mcp(self.ctx)
            _all_tools: int = len(_fs.registry.get_all_tool_names())
            logger.info("Sandbox + %d tools initialized | mode=%s",
                        _all_tools, self.ctx.mode)
        except Exception as exc:
            logger.warning("Sandbox/tools unavailable: %s", exc)
            self._shutdown_event.set()

        # ---- 初始化 skills 目录 ----
        _skills_dir: Path = Path("skills")
        _skills_dir.mkdir(parents=True, exist_ok=True)
        _seed: Path = _skills_dir / "self-evolution" / "SKILL.md"
        if not _seed.exists():
            _seed.parent.mkdir(parents=True, exist_ok=True)
            _seed.write_text("""---
name: self-evolution
description: "Evolve Agent Self-Evolution Guide"
category: core
---

# Self-Evolution

You can modify your own source code and complete evolution through the following tools:

1. Use the filesystem tool to read source code from ``fork:``
2. ``write_fork`` or ``edit_file`` — write evolved code to fork: or ws:
3. ``validate_code`` — check syntax
4. ``diff_fast_fork`` — diff fast fork and save diff file
5. ``evolve_code`` — deep validate and trigger swap
""", encoding="utf-8")
            logger.info("Seeded skill: self-evolution")

        # ---- 创建 Application 单例并装配子系统 ----
        from system.application import Application, ApprovalBackendManager
        from gateway.session_manager import SessionManager
        from component.cron_router import CronRouter
        from abstract.tools.registry import registry as tool_registry

        app = Application(self.ctx)
        app.session_manager = SessionManager(str(self.ctx.workspace / "sessions"))
        app.approval_backend_manager = ApprovalBackendManager(self.ctx)
        app.cron_router = CronRouter()
        app.tool_registry = tool_registry
        # 绑定关闭事件，供子系统优雅退出使用
        app.link_shutdown_event(self._shutdown_event)
        # _app 已在 Application.__init__ 中设为全局单例

        # ---- 创建 agent 循环 ----
        agent_loop: AgentLoop | None = None
        try:
            from entry.parent_agent_loop import ParentAgentLoop as AgentLoop
            from entry.agent_sink import FrontendSink
            history_path: str = str(self.ctx.workspace / "sessions")
            agent_loop = AgentLoop(
                Application.current(),
                session_id="__bootstrap__",
                frontend_sink=FrontendSink(),
                history_store_dir=Path(history_path) if history_path else None,
            )

            # 注册持久化 memory provider
            try:
                from memory.provider import EasysaveMemoryProvider
                mem: EasysaveMemoryProvider = EasysaveMemoryProvider(
                    memory_dir=self.ctx.workspace / "memory"
                )
                agent_loop.add_memory_provider(mem)
                logger.info("EasysaveMemoryProvider registered")
            except Exception as exc:
                logger.warning("Memory provider unavailable: %s", exc)

            # 将工具事件流连接到前端
            from gateway.server import _send_tool_event
            agent_loop.set_tool_event_callback(_send_tool_event)
            set_agent_loop(agent_loop)
            set_dashboard_agent_loop(agent_loop)
            set_agentspace_path(self.ctx.agentspace)

            # ---- 创建 SubAgentOrchestrator ----
            try:
                from subagent.orchestrator import SubAgentOrchestrator
                orch = SubAgentOrchestrator()
                orch.set_agent_loop(agent_loop)
                Application.current().subagent_orchestrator = orch
                logger.info("SubAgentOrchestrator initialized")
            except Exception as exc:
                logger.debug("SubAgentOrchestrator not available: %s", exc)

            logger.info("AgentLoop initialized | model=%s", self.ctx.llm_model)
        except Exception as exc:
            logger.warning("AgentLoop unavailable: %s", exc)
            # Gateway 将回退到 echo 模式

        # ---- 预编译 llama-server（本地脱手模式审批模型需要）----
        _local_disabled = {"", "false", "0", "no"}
        _local_path_raw = (self.ctx.approval_model_path or "").strip().lower()
        if _local_path_raw not in _local_disabled:
            from system.pathutils import find_repo_root
            gguf_path = find_repo_root() / CUSTOM_MODELS_DIR / self.ctx.approval_model_path.strip()
            if gguf_path.is_file():
                try:
                    from third.llamaapis.system.builder import LlamaBuilder
                    _builder = LlamaBuilder(
                        source_dir="lib/llama.cpp",
                        cuda=self.ctx.approval_model_cuda,
                        jobs=4,
                    )
                    await asyncio.to_thread(_builder.build_if_needed)
                except Exception as exc:
                    logger.warning(
                        "llama-server pre-build failed (will retry at runtime): %s", exc
                    )
            else:
                logger.warning(
                    "Local approval model file not found: %s — skipping llama.cpp pre-build",
                    gguf_path,
                )

        host: str = self.ctx.gateway_host
        port: int = self.ctx.gateway_port
        self._gateway_server = create_server(host=host, port=port)
        self._gateway_task = asyncio.create_task(
            self._gateway_server.serve(),  # type: ignore[union-attr]
            name="gateway-server",
        )
        # 给 server 一点时间完成端口绑定
        await asyncio.sleep(0.5)

        logger.info("Gateway listening on ws://%s:%d/ws/chat", host, port)
        logger.info("WebPage on http://127.0.0.1:%d", port)

        # ---- 自动打开浏览器 ----
        # import webbrowser
        # _browser_host: str = "127.0.0.1" if host in ("0.0.0.0", "::") else host
        # _url: str = f"http://{_browser_host}:{port}"
        # try:
        #     webbrowser.open(_url)
        #     logger.info("Browser opened: %s", _url)
        # except Exception as exc:
        #     logger.warning("Failed to open browser: %s", exc)

    async def _stop_gateway(self) -> None:
        """优雅停止 gateway server。"""
        if self._gateway_server is None or self._gateway_task is None:
            return
        logger.info("Gateway shutting down...")
        # 先停止所有子 Agent 会话
        try:
            from gateway.server import shutdown_subagent_orchestrator
            await shutdown_subagent_orchestrator()
        except Exception:
            logger.warning("Failed to shutdown subagent orchestrator", exc_info=True)
        # 关闭 MCP server 连接（释放子进程、后台线程）
        try:
            import component.mcp_tools
            component.mcp_tools.shutdown_mcp()
        except Exception:
            logger.warning("Failed to shutdown MCP tools", exc_info=True)
        self._gateway_server.should_exit = True  # type: ignore[union-attr]
        self._gateway_task.cancel()
        try:
            await self._gateway_task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning("Failed to await gateway task during shutdown", exc_info=True)
        logger.info("Gateway stopped")

    async def _drain_background_tasks(self, timeout: float = 5.0) -> None:
        """返回前等待所有待处理 asyncio task 完成。

        防止进程以退出码 -1（进化）退出时，
        正在进行的 I/O（session 索引写入、消息持久化、
        工具事件流等）被截断。
        """
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        pending: list[asyncio.Task] = [
            t for t in asyncio.all_tasks(loop)
            if t is not asyncio.current_task() and not t.done()
        ]
        if not pending:
            return

        for t in pending:
            name = t.get_name()
            if not name or name.startswith("Task-") or name == "Task":
                coro = t.get_coro()
                name = getattr(coro, "__qualname__", None) or getattr(coro, "__name__", repr(coro))
            logger.info("  pending background task: %s", name)

        logger.info("Draining %d background task(s)...", len(pending))
        try:
            await asyncio.wait_for(
                asyncio.gather(*pending, return_exceptions=True),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            still_pending = [
                t for t in asyncio.all_tasks(loop)
                if t is not asyncio.current_task() and not t.done()
            ]
            for t in still_pending:
                name = t.get_name()
                if not name or name.startswith("Task-") or name == "Task":
                    coro = t.get_coro()
                    name = getattr(coro, "__qualname__", None) or getattr(coro, "__name__", repr(coro))
                logger.warning("  task still running after timeout: %s", name)
            logger.warning(
                "Some background tasks did not complete within %.1fs",
                timeout,
            )