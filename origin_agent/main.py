"""App lifecycle — the single async entry point for the agent process.

Does NOT import any heavy subsystems at module level.  Everything is
lazily wired inside ``App.run()`` so import errors surface cleanly.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from system.context import RuntimeContext

logger = logging.getLogger(__name__)


class App:
    """Thin async runner.  Created by __main__.py with a RuntimeContext,
    then ``await app.run()`` blocks until shutdown.
    """

    def __init__(self, ctx: RuntimeContext) -> None:
        self.ctx = ctx
        self._shutdown_event = asyncio.Event()
        self._gateway_server: object | None = None
        self._gateway_task: asyncio.Task[None] | None = None

    async def run(self) -> int:
        """Block until shutdown is requested.  Returns an exit code."""
        logger.info(
            "App starting | mode=%s workspace=%s self=%s fork=%s",
            self.ctx.mode,
            self.ctx.workspace,
            self.ctx.self_path,
            self.ctx.fork_path,
        )

        # ---- start gateway ----
        await self._start_gateway()

        # ---- signal handling ----
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._request_shutdown)
            except NotImplementedError:
                pass  # Windows does not support add_signal_handler

        await self._shutdown_event.wait()

        # ---- stop gateway ----
        await self._stop_gateway()

        logger.info("App shutdown complete")
        return 0

    def _request_shutdown(self) -> None:
        logger.info("Shutdown requested")
        self._shutdown_event.set()

    # -- gateway lifecycle --------------------------------------------------

    async def _start_gateway(self) -> None:
        """Create uvicorn server and run it as a background task."""
        try:
            from gateway.server import create_server, set_agent_loop
        except ImportError as exc:
            logger.warning("Gateway unavailable (import error): %s", exc)
            return

        # ---- initialize sandbox + tools ----
        try:
            from system.sandbox import Sandbox
            _sandbox = Sandbox(self.ctx)
            import component.tools.filesystem as _fs
            _fs.set_sandbox(_sandbox)
            import component.tools  # noqa: F401 — triggers registry.register()
            logger.info("Sandbox + %d tools initialized | mode=%s",
                        len(component.tools.filesystem.registry.get_all_tool_names()),
                        self.ctx.mode)
        except Exception as exc:
            logger.warning("Sandbox/tools unavailable: %s", exc)

        # ---- create agent loop ----
        try:
            from entry.agent import AgentLoop
            agent_loop = AgentLoop(self.ctx)
            set_agent_loop(agent_loop)
            logger.info("AgentLoop initialized | model=%s", self.ctx.llm_model)
        except Exception as exc:
            logger.warning("AgentLoop unavailable: %s", exc)
            # Gateway will fall back to echo mode

        host = self.ctx.gateway_host
        port = self.ctx.gateway_port
        self._gateway_server = create_server(host=host, port=port)
        self._gateway_task = asyncio.create_task(
            self._gateway_server.serve()  # type: ignore[union-attr]
        )
        # Give the server a moment to bind
        await asyncio.sleep(0.5)
        logger.info("Gateway listening on ws://%s:%d/ws/chat", host, port)

    async def _stop_gateway(self) -> None:
        """Gracefully stop the gateway server."""
        if self._gateway_server is None or self._gateway_task is None:
            return
        logger.info("Gateway shutting down...")
        self._gateway_server.should_exit = True  # type: ignore[union-attr]
        self._gateway_task.cancel()
        try:
            await self._gateway_task
        except (asyncio.CancelledError, Exception):
            pass
        logger.info("Gateway stopped")