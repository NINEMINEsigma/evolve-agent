from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Coroutine, TypeVar

from fastapi import FastAPI
from framework import AsyncSystem
from system.lifecycle import TaskOwner

from .runtime_system import IRuntimeSystem

if TYPE_CHECKING:
    from gateway.lifecycle import GatewayAdmission, GatewayReadyTracker

WorkT = TypeVar("WorkT")


class IGatewaySystem(AsyncSystem, ABC):
    """Declare Gateway application, admission and server lifecycle operations."""

    @property
    @abstractmethod
    def fastapi_app(self) -> FastAPI:
        """Return the constructed FastAPI application."""
        ...

    @property
    @abstractmethod
    def admission(self) -> GatewayAdmission:
        """Return the Gateway business-admission controller."""
        ...

    @property
    @abstractmethod
    def ready_tracker(self) -> GatewayReadyTracker:
        """Return the startup readiness tracker."""
        ...

    @property
    @abstractmethod
    def task_owner(self) -> TaskOwner:
        """Return the owner for Gateway background tasks."""
        ...

    @property
    @abstractmethod
    def runtime(self) -> IRuntimeSystem:
        """Return the runtime service used by Gateway."""
        ...

    @abstractmethod
    def spawn_work(
        self,
        coro: Coroutine[Any, Any, WorkT],
        *,
        name: str,
    ) -> asyncio.Task[WorkT]:
        """Register one route background coroutine with Gateway ownership."""
        ...

    @abstractmethod
    def stop_accepting(self) -> None:
        """Close Gateway admission while preserving existing output connections."""
        ...

    @abstractmethod
    async def cancel_background_work(self) -> None:
        """Cancel and await Gateway route background work."""
        ...

    @abstractmethod
    async def stop_server(self) -> None:
        """Stop uvicorn and close the Gateway socket."""
        ...
