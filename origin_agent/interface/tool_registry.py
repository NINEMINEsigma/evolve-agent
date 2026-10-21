from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, TypeAlias

from entity.puretype import (
    ToolAvailability,
    ToolBatchDecision,
    ToolCallRequest,
    ToolDangerLevel,
)
from framework import AsyncSystem
from system.lifecycle import TaskOwner

from .runtime_system import IRuntimeSystem

if TYPE_CHECKING:
    from abstract.tools.tool import (
        BaseTool,
        BaseToolSet,
        ToolExecution,
        ToolPostprocessEffect,
    )

JSONValue: TypeAlias = (
    str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]
)
ToolPayload: TypeAlias = dict[str, JSONValue]


class IToolRegistry(AsyncSystem, ABC):
    """Declare object-tool registration, filtering, execution and cleanup."""

    @property
    @abstractmethod
    def runtime(self) -> IRuntimeSystem:
        """Return the runtime admission and failure service."""
        ...

    @property
    @abstractmethod
    def task_owner(self) -> TaskOwner:
        """Return the owner for asynchronous tool requests."""
        ...

    @abstractmethod
    def get_tool(self, name: str) -> BaseTool | None:
        """Return the registered tool object by name."""
        ...

    @abstractmethod
    def plan_tool_batch(self, tool_calls: list[ToolCallRequest]) -> ToolBatchDecision:
        """Apply accepts-following-calls rules to one model tool batch."""
        ...

    @abstractmethod
    def register_tool(
        self,
        tool: BaseTool,
        *,
        replace: bool = False
        ) -> None:
        """Register one tool object atomically."""
        ...

    @abstractmethod
    def get_schema(self, name: str) -> ToolPayload | None:
        """Return one tool's raw schema payload."""
        ...

    @abstractmethod
    def get_all_tool_names(self) -> list[str]:
        """Return all registered tool names in stable order."""
        ...

    @abstractmethod
    def get_toolset_for_tool(self, name: str) -> str | None:
        """Return the toolset owning one registered tool."""
        ...

    @abstractmethod
    def get_availability(self, name: str) -> ToolAvailability:
        """Return one tool's availability scope."""
        ...

    @abstractmethod
    def get_definitions_for_availability(
        self,
        scope: ToolAvailability,
        tool_names: set[str] | None = None,
        quiet: bool = False
        ) -> list[ToolPayload]:
        """Build schemas filtered by availability and runtime checks."""
        ...

    @abstractmethod
    def get_danger_level(self, name: str) -> ToolDangerLevel:
        """Return one tool's declared danger level."""
        ...

    @abstractmethod
    def is_tool_available(self, name: str) -> bool:
        """Evaluate one tool's current availability check."""
        ...

    @abstractmethod
    def get_tool_to_toolset_map(self) -> dict[str, str]:
        """Return the registered tool-to-toolset mapping."""
        ...

    @abstractmethod
    def get_registered_toolset_names(self) -> list[str]:
        """Return registered toolset names in stable order."""
        ...

    @abstractmethod
    def get_tool_names_for_toolset(self, toolset: str) -> list[str]:
        """Return registered tool names belonging to one toolset."""
        ...

    @abstractmethod
    def register_toolset_alias(
        self,
        alias: str,
        toolset: str
        ) -> None:
        """Register one explicit toolset alias."""
        ...

    @abstractmethod
    def get_registered_toolset_aliases(self) -> dict[str, str]:
        """Return the current toolset alias mapping."""
        ...

    @abstractmethod
    def get_toolset_alias_target(self, alias: str) -> str | None:
        """Resolve one toolset alias to its canonical name."""
        ...

    @abstractmethod
    def register_toolset(
        self,
        toolset: BaseToolSet,
        *,
        merge: bool = False
        ) -> None:
        """Preheat and register one toolset declaration."""
        ...

    @abstractmethod
    def deregister_toolset(self, name: str) -> None:
        """Remove toolset metadata after its tools are removed."""
        ...

    @abstractmethod
    def get_toolset(self, name: str) -> BaseToolSet | None:
        """Return registered toolset metadata by name."""
        ...

    @abstractmethod
    def deregister(self, name: str) -> None:
        """Remove one registered tool object by name."""
        ...

    @abstractmethod
    def get_definitions(
        self,
        tool_names: set[str],
        quiet: bool = False
        ) -> list[ToolPayload]:
        """Build schemas for the requested tool names."""
        ...

    @abstractmethod
    def get_definitions_for_loaded_toolsets(
        self,
        scope: ToolAvailability,
        loaded_toolsets: set[str],
        quiet: bool = False
        ) -> list[ToolPayload]:
        """Build schemas filtered by loaded toolsets and availability."""
        ...

    @abstractmethod
    def get_toolset_catalog(
        self,
        scope: ToolAvailability,
        loaded_toolsets: set[str]
        ) -> list[ToolPayload]:
        """Build the visible toolset catalog for one Agent scope."""
        ...

    @abstractmethod
    def close_dispatch(self) -> None:
        """Reject new tool dispatches while allowing cleanup."""
        ...

    @abstractmethod
    def dispatch(self, execution: ToolExecution) -> ToolExecution:
        """Execute one synchronous tool outside the event loop."""
        ...

    @abstractmethod
    async def async_dispatch(self, execution: ToolExecution) -> ToolExecution:
        """Execute one approved tool invocation asynchronously."""
        ...

    @abstractmethod
    async def async_postprocess(self, execution: ToolExecution) -> ToolPostprocessEffect:
        """Run one tool's post-commit phase under registry ownership."""
        ...

    @abstractmethod
    async def cancel_pending_calls(self) -> None:
        """Cancel and await pending tool requests."""
        ...

    @abstractmethod
    async def wait_idle(self) -> None:
        """Wait for requests and native synchronous tool work to finish."""
        ...

    @abstractmethod
    def get_max_result_size(
        self,
        name: str,
        default: int | None = None
        ) -> int:
        """Return the configured result-size limit for one tool."""
        ...

    @abstractmethod
    def is_toolset_available(self, toolset: str) -> bool:
        """Evaluate one toolset's environment requirements."""
        ...

    @abstractmethod
    def check_toolset_requirements(self) -> dict[str, bool]:
        """Return availability for all registered toolsets."""
        ...

    @abstractmethod
    def get_available_toolsets(self) -> dict[str, ToolPayload]:
        """Return toolset metadata and availability details."""
        ...

    @abstractmethod
    def get_toolset_requirements(self) -> dict[str, ToolPayload]:
        """Return toolset environment requirement metadata."""
        ...

    @abstractmethod
    def check_tool_availability(self, quiet: bool = False) -> tuple[list[str], list[ToolPayload]]:
        """Return available toolsets and unavailable requirement details."""
        ...
