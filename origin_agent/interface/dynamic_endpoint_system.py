from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from entity.puretype.extools import DynamicEndpointInfo
from framework import AsyncSystem

from .runtime_system import IRuntimeSystem
from .session_manager import ISessionManager


class IDynamicEndpointSystem(AsyncSystem, ABC):
    """Declare dynamic endpoint registration and session migration operations."""

    @property
    @abstractmethod
    def runtime(self) -> IRuntimeSystem:
        """Return the runtime admission service."""
        ...

    @property
    @abstractmethod
    def session_manager(self) -> ISessionManager:
        """Return the owning session manager."""
        ...

    @property
    @abstractmethod
    def store_path(self) -> Path:
        """Return the persistent dynamic-endpoint store path."""
        ...

    @abstractmethod
    def close_admission(self) -> None:
        """Reject new endpoint mutations during shutdown."""
        ...

    @abstractmethod
    def lookup_endpoint(self, endpoint_name: str) -> DynamicEndpointInfo | None:
        """Look up one endpoint by its globally unique name."""
        ...

    @abstractmethod
    def list_session_endpoints(
        self,
        session_id: str,
        agent_name: str | None = None
        ) -> list[dict[str, str | float]]:
        """List endpoints belonging to one session and optional Agent."""
        ...

    @abstractmethod
    def register_endpoint(
        self,
        session_id: str,
        agent_name: str,
        name: str
        ) -> DynamicEndpointInfo:
        """Register and persist one endpoint."""
        ...

    @abstractmethod
    def unregister_endpoint(self, name: str) -> DynamicEndpointInfo:
        """Remove and persist one endpoint by name."""
        ...

    @abstractmethod
    def migrate_session_endpoints(
        self,
        old_sid: str,
        new_sid: str
        ) -> int:
        """Move all endpoint ownership from one session to another."""
        ...

    @abstractmethod
    def cleanup_session_endpoints(self, session_id: str) -> int:
        """Remove all endpoint records belonging to one deleted session."""
        ...
