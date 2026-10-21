from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from entity.constant import SEARCH_PROCESS_STDERR_MAX_BYTES, Namespace
from entity.puretype import DynamicSandboxSpace, ProcessLineStreamResult
from framework import AsyncSystem

if TYPE_CHECKING:
    from system.context import RuntimeContext
    from system.sandbox import Access, ResolvedPath


class ISandbox(AsyncSystem, ABC):
    """Declare logical path, dynamic-space and subprocess sandbox operations."""

    @property
    @abstractmethod
    def context(self) -> RuntimeContext:
        """Return the immutable runtime context owned by the sandbox."""
        ...

    @property
    @abstractmethod
    def agentspace(self) -> Path:
        """Return the physical ws namespace root."""
        ...

    @abstractmethod
    def list_dynamic_spaces(self) -> list[DynamicSandboxSpace]:
        """Return configured dynamic spaces as independent snapshots."""
        ...

    @abstractmethod
    def list_dynamic_spaces_with_availability(self) -> list[tuple[DynamicSandboxSpace, bool]]:
        """Return dynamic-space snapshots with current directory availability."""
        ...

    @abstractmethod
    def normalize_dynamic_space_path(self, raw_path: str) -> str:
        """Normalize and validate a dynamic-space absolute path."""
        ...

    @abstractmethod
    def add_dynamic_space(
        self,
        *,
        name: str,
        path: str,
        description: str,
        is_readonly: bool,
        session_id: str = ""
        ) -> tuple[DynamicSandboxSpace, bool]:
        """Add one fast-mode dynamic space idempotently."""
        ...

    @abstractmethod
    def update_dynamic_space(
        self,
        name: str,
        *,
        path: str,
        description: str,
        is_readonly: bool,
        session_id: str = ""
        ) -> DynamicSandboxSpace:
        """Update one dynamic space without changing its name."""
        ...

    @abstractmethod
    def remove_dynamic_space(
        self,
        name: str,
        *,
        session_id: str = ""
        ) -> bool:
        """Remove one dynamic space idempotently."""
        ...

    @abstractmethod
    def is_namespaced_path(self, path: str) -> bool:
        """Check whether a logical path uses a configured namespace."""
        ...

    @abstractmethod
    def resolve(
        self,
        logical: str,
        access: Access
        ) -> ResolvedPath:
        """Resolve a logical path after namespace and access validation."""
        ...

    @abstractmethod
    def resolve_read(self, logical: str) -> ResolvedPath:
        """Resolve a logical path for read access."""
        ...

    @abstractmethod
    def resolve_write(self, logical: str) -> ResolvedPath:
        """Resolve a logical path for write access."""
        ...

    @abstractmethod
    def namespace_bases(self) -> dict[str, Path]:
        """Return currently available namespace roots."""
        ...

    @abstractmethod
    def get_base(self, ns: Namespace) -> Path:
        """Return one namespace's physical root."""
        ...

    @abstractmethod
    def run(
        self,
        args: list[str],
        *,
        cwd_ns: str = "ws:",
        timeout: int | None = None,
        extra_env: dict[str, str] | None = None,
        session_id: str = ""
        ) -> subprocess.CompletedProcess:
        """Run a synchronous subprocess inside the logical sandbox."""
        ...

    @abstractmethod
    async def run_async(
        self,
        args: list[str],
        *,
        cwd_ns: str = "ws:",
        timeout: int | None = None,
        extra_env: dict[str, str] | None = None,
        session_id: str = ""
        ) -> subprocess.CompletedProcess:
        """Run a subprocess asynchronously inside the logical sandbox."""
        ...

    @abstractmethod
    async def run_async_line_processor(
        self,
        args: list[str],
        *,
        cwd_ns: str = "ws:",
        on_stdout_line: Callable[[bytes], bool],
        timeout: int | None = None,
        extra_env: dict[str, str] | None = None,
        session_id: str = "",
        stderr_byte_limit: int = SEARCH_PROCESS_STDERR_MAX_BYTES
        ) -> ProcessLineStreamResult:
        """Consume sandboxed subprocess output line by line."""
        ...

    @abstractmethod
    def kill_active(self, session_id: str) -> None:
        """Request termination of all sandbox processes owned by a session."""
        ...

    @abstractmethod
    def read(
        self,
        logical: str,
        offset: int = 0,
        limit: int = 100,
        *,
        strict_utf8: bool = False
        ) -> str:
        """Read a sandbox file with line pagination and encoding policy."""
        ...

    @abstractmethod
    def ensure_parent_directories(self, logical: str) -> list[str]:
        """Create missing parent directories and return their logical paths."""
        ...

    @abstractmethod
    def write(
        self,
        logical: str,
        content: str
        ) -> None:
        """Write text to a sandbox path without newline normalization."""
        ...

    @abstractmethod
    def append(
        self,
        logical: str,
        content: str
        ) -> None:
        """Append text to an existing sandbox file."""
        ...

    @abstractmethod
    def exists(self, logical: str) -> bool:
        """Check whether a logical sandbox path exists."""
        ...

    @abstractmethod
    def list_dir(self, logical: str) -> list[str]:
        """List one logical sandbox directory."""
        ...

    @abstractmethod
    def copy(
        self,
        logical_src: str,
        logical_dst: str
        ) -> ResolvedPath:
        """Copy one sandbox file and return its actual destination."""
        ...

    @abstractmethod
    def copy_folder(
        self,
        logical_src: str,
        logical_dst: str
        ) -> ResolvedPath:
        """Copy one sandbox directory and return its destination."""
        ...

    @abstractmethod
    def move(
        self,
        logical_src: str,
        logical_dst: str
        ) -> ResolvedPath:
        """Move one sandbox path and return its actual destination."""
        ...

    @abstractmethod
    def delete(self, logical: str) -> None:
        """Delete one sandbox file or empty directory."""
        ...

    @abstractmethod
    def resolve_abs(self, logical: str) -> str:
        """Resolve a logical path to an absolute physical string."""
        ...

    @abstractmethod
    def create_folder(
        self,
        logical: str,
        parents: bool = True
        ) -> None:
        """Create one sandbox directory."""
        ...

    @abstractmethod
    def delete_folder(self, logical: str) -> None:
        """Recursively delete one sandbox directory."""
        ...

    @abstractmethod
    def is_file(self, logical: str) -> bool:
        """Check whether a logical path is a file."""
        ...

    @abstractmethod
    def is_dir(self, logical: str) -> bool:
        """Check whether a logical path is a directory."""
        ...

    @abstractmethod
    def count_lines(self, logical: str) -> int:
        """Count logical file lines without changing file contents."""
        ...
