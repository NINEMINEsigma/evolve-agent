"""Gateway endpoint component contract without request-local state."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, TypeVar

from entity.constant import GATEWAY_API_DEFAULT_PRIORITY

from fastapi import APIRouter
from framework import AsyncComponent, AsyncSystem

from .gateway_system import IGatewaySystem

SystemT = TypeVar("SystemT", bound=AsyncSystem)


class APIComponent(AsyncComponent, ABC):
    """Bind one endpoint implementation to its owning Gateway System."""

    priority: ClassVar[int] = GATEWAY_API_DEFAULT_PRIORITY

    @property
    def gateway(self) -> IGatewaySystem:
        parent = self.parent_system
        if not isinstance(parent, IGatewaySystem):
            raise RuntimeError("API component is not bound to a Gateway System")
        return parent

    def get_system(self, system_type: type[SystemT]) -> SystemT:
        return self.gateway.get_system(system_type)

    @abstractmethod
    def display(self, router: APIRouter) -> None:
        """Register the bound handler with explicit protocol metadata."""
        ...

    @abstractmethod
    def handler(self, *args: Any, **kwargs: Any) -> Any:
        """Handle one request; concrete signatures are inspected by FastAPI."""
        ...
