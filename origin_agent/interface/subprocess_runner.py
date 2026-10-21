from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from typing import Callable

from entity.constant import SEARCH_PROCESS_STDERR_MAX_BYTES
from entity.puretype.runtime import ProcessLineStreamResult
from framework import AsyncSystem

from .runtime_system import IRuntimeSystem


class ISubprocessRunner(AsyncSystem, ABC):
    """Declare sandboxed subprocess execution and shutdown ownership."""

    @property
    @abstractmethod
    def runtime(self) -> IRuntimeSystem:
        """Return the runtime admission and failure-reporting service."""
        ...

    @abstractmethod
    def close_admission(self) -> None:
        """Reject new subprocess operations."""
        ...

    @abstractmethod
    async def terminate_all(self) -> None:
        """Terminate all owned subprocesses and await their cleanup."""
        ...

    @abstractmethod
    async def wait_idle(self) -> None:
        """Wait until owned subprocess operations and processes are idle."""
        ...

    @abstractmethod
    def run(
        self,
        args: list[str],
        *,
        cwd: str,
        timeout: float | None = None,
        extra_env: dict[str, str] | None = None,
        session_id: str = "",
    ) -> subprocess.CompletedProcess[str]:
        """Run a blocking subprocess with session ownership."""
        ...

    @abstractmethod
    async def run_async(
        self,
        args: list[str],
        *,
        cwd: str,
        timeout: float | None = None,
        extra_env: dict[str, str] | None = None,
        session_id: str = "",
    ) -> subprocess.CompletedProcess[str]:
        """Run a subprocess asynchronously without blocking the event loop."""
        ...

    @abstractmethod
    async def run_async_line_processor(
        self,
        args: list[str],
        *,
        cwd: str,
        on_stdout_line: Callable[[bytes], bool],
        timeout: float | None = None,
        extra_env: dict[str, str] | None = None,
        session_id: str = "",
        stderr_byte_limit: int = SEARCH_PROCESS_STDERR_MAX_BYTES,
    ) -> ProcessLineStreamResult:
        """Consume subprocess stdout line by line with bounded stderr."""
        ...

    @abstractmethod
    def kill_active(self, session_id: str) -> None:
        """Request termination of processes owned by one session."""
        ...
