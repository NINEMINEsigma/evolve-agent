from __future__ import annotations

from abc import ABC, abstractmethod

from .runtime_system import IDPRuntimeSystem


class IMCPSystem(IDPRuntimeSystem, ABC):
    """Declare MCP refresh, status and shutdown admission operations."""

    @abstractmethod
    async def refresh(self) -> dict[str, dict[str, str | int | float | bool | None]]:
        """Reload configured MCP servers and return refresh details."""
        ...

    @abstractmethod
    def status(self) -> list[dict[str, str | int | float | bool | None]]:
        """Return a serializable status snapshot for configured MCP servers."""
        ...

    @abstractmethod
    def close_admission(self) -> None:
        """Reject new MCP work while preserving cleanup ownership."""
        ...

    @abstractmethod
    async def stop_calls(self) -> None:
        """Stop active MCP calls and wait for native work to finish."""
        ...
