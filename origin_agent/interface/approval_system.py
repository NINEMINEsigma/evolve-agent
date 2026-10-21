from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from entity.messages import BaseMessage
from framework import AsyncSystem

if TYPE_CHECKING:
    from component.approval.allowlist import ToolAllowlistStore
    from component.approval.manager import ApprovalBackendManager
    from component.approval.mode_store import ApprovalModeStore


class IApprovalSystem(AsyncSystem, ABC):
    """Declare approval mode, backend and model-request operations."""

    @property
    @abstractmethod
    def mode_store(self) -> ApprovalModeStore:
        """Return the session approval-mode store."""
        ...

    @property
    @abstractmethod
    def backend_manager(self) -> ApprovalBackendManager:
        """Return the approval backend manager."""
        ...

    @property
    @abstractmethod
    def allowlist(self) -> ToolAllowlistStore:
        """Return the persistent tool allowlist store."""
        ...

    @abstractmethod
    async def chat(self, messages: list[BaseMessage]) -> str:
        """Ask the configured approval model to evaluate messages."""
        ...

    @abstractmethod
    def close_admission(self) -> None:
        """Reject new approval requests during shutdown."""
        ...

    @abstractmethod
    async def cancel_pending(self) -> None:
        """Cancel and await all in-flight approval requests."""
        ...
