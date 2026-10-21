from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from entity.puretype import LSPDefinition, LSPDiagnostic, LSPReference, LSPState, LSPSymbol
from framework import AsyncSystem

from .runtime_system import IRuntimeSystem
from .sandbox import ISandbox


class ILSPManager(AsyncSystem, ABC):
    """Declare language-server startup, query and diagnostic operations."""

    @property
    @abstractmethod
    def runtime(self) -> IRuntimeSystem:
        """Return the runtime event-loop and failure service."""
        ...

    @property
    @abstractmethod
    def sandbox(self) -> ISandbox:
        """Return the sandbox used to map logical source paths."""
        ...

    @abstractmethod
    def close_admission(self) -> None:
        """Reject new language-server requests during shutdown."""
        ...

    @property
    @abstractmethod
    def state(self) -> LSPState:
        """Return the current language-server lifecycle state."""
        ...

    @abstractmethod
    def is_ready(self) -> bool:
        """Report whether pyright is ready for queries."""
        ...

    @abstractmethod
    def get_root_uri(self) -> str | None:
        """Return the current language-server workspace URI."""
        ...

    @abstractmethod
    def start(self, root_logical: str) -> dict[str, str | bool]:
        """Start or replace the server for one logical workspace root."""
        ...

    @abstractmethod
    async def references(self, logical_path: str, line: int, column: int) -> list[LSPReference]:
        """Return symbol references at a logical source position."""
        ...

    @abstractmethod
    async def definition(self, logical_path: str, line: int, column: int) -> LSPDefinition | None:
        """Return the symbol definition at a logical source position."""
        ...

    @abstractmethod
    async def diagnostics(self, logical_path: str) -> list[LSPDiagnostic]:
        """Return cached diagnostics for one logical source path."""
        ...

    @abstractmethod
    async def symbols(self, logical_path: str) -> list[LSPSymbol]:
        """Return document symbols for one logical source path."""
        ...

    @abstractmethod
    async def refresh(self, logical_path: str | None) -> dict[str, str | bool]:
        """Refresh the server view of one path or the full workspace."""
        ...

    @abstractmethod
    def notify_did_change(self, logical_path: str, content: str) -> None:
        """Notify the server about a changed logical source file."""
        ...

    @abstractmethod
    def get_cached_diagnostics(self, uri: str) -> list[LSPDiagnostic]:
        """Return diagnostics cached under a resolved document URI."""
        ...

    @abstractmethod
    def is_in_workspace(self, real_path: Path) -> bool:
        """Check whether a physical path belongs to the active workspace."""
        ...
