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
    from origin_agent.system.context import RuntimeContext

logger = logging.getLogger(__name__)


class App:
    """Thin async runner.  Created by __main__.py with a RuntimeContext,
    then ``await app.run()`` blocks until shutdown.
    """

    def __init__(self, ctx: RuntimeContext) -> None:
        self.ctx = ctx
        self._shutdown_event = asyncio.Event()

    async def run(self) -> int:
        """Block until shutdown is requested.  Returns an exit code.

        Currently a skeleton — just prints startup info and waits
        for SIGINT / SIGTERM.
        """
        logger.info(
            "App starting | mode=%s workspace=%s self=%s fork=%s",
            self.ctx.mode,
            self.ctx.workspace,
            self.ctx.self_path,
            self.ctx.fork_path,
        )

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._request_shutdown)
            except NotImplementedError:
                pass  # Windows does not support add_signal_handler

        await self._shutdown_event.wait()
        logger.info("App shutdown complete")
        return 0

    def _request_shutdown(self) -> None:
        logger.info("Shutdown requested")
        self._shutdown_event.set()