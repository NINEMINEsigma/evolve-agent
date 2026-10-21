from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from entity.constant import CDP_ENDPOINT_DEFAULT
from framework import AsyncSystem
from system.lifecycle import TaskOwner

from .runtime_system import IRuntimeSystem

if TYPE_CHECKING:
    from playwright.async_api import Browser


class IBrowserSystem(AsyncSystem, ABC):
    """Declare browser connection and application-owned process cleanup."""

    @property
    @abstractmethod
    def runtime(self) -> IRuntimeSystem:
        """Return the runtime service used for browser admission."""
        ...

    @property
    @abstractmethod
    def task_owner(self) -> TaskOwner:
        """Return the owner for browser requests."""
        ...

    @abstractmethod
    def current_endpoint(self) -> str:
        """Return the currently selected CDP endpoint."""
        ...

    @abstractmethod
    async def get_browser(self, endpoint: str = CDP_ENDPOINT_DEFAULT) -> Browser:
        """Connect to the requested CDP endpoint without launching a browser."""
        ...

    @abstractmethod
    async def teardown(self) -> None:
        """Release the current CDP and Playwright connections."""
        ...

    @abstractmethod
    def register_headless_proc(self, proc: subprocess.Popen) -> None:
        """Register an application-owned headless browser process."""
        ...

    @abstractmethod
    async def cleanup_headless_browser(self) -> int:
        """Terminate and reap all registered headless processes."""
        ...

    @abstractmethod
    def close_admission(self) -> None:
        """Reject new browser requests during shutdown."""
        ...
