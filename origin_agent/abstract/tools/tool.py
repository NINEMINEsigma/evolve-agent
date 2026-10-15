"""Object tools and non-persistent, invocation-owned phase materials."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from entity.messages import ToolResultMessage
from entity.puretype import ToolAvailability, ToolDangerLevel

if TYPE_CHECKING:
    from entry.base_agent_loop import ToolContext


class ToolHandlerResult:
    """Keep the public result separate from private invocation state."""

    def __init__(self, result: dict[str, Any], state: Any = None) -> None:
        self.result = result
        self.state = state


class ToolPostprocessEffect:
    """Carry completed postprocessing effects back to the owning Loop."""

    def __init__(
        self,
        *,
        suppress_tool_result_event: bool = False,
        discarded_tool_call_ids: tuple[str, ...] = (),
        replacement_result: dict[str, Any] | None = None,
        stop_current_round: bool = False,
        loop_replaced: bool = False,
        evolution_requested: bool = False,
        completion_message: str | None = None,
        system_message: str | None = None,
    ) -> None:
        self.suppress_tool_result_event = suppress_tool_result_event
        self.discarded_tool_call_ids = discarded_tool_call_ids
        self.replacement_result = replacement_result
        self.stop_current_round = stop_current_round
        self.loop_replaced = loop_replaced
        self.evolution_requested = evolution_requested
        self.completion_message = completion_message
        self.system_message = system_message


class ToolExecution:
    """Hold mutable state for exactly one call, never on a shared tool instance."""

    def __init__(
        self,
        *,
        tool: BaseTool,
        arguments: dict[str, Any],
        context: ToolContext,
        tool_call_id: str,
    ) -> None:
        self.tool = tool
        self.arguments = arguments
        self.context = context
        self.tool_call_id = tool_call_id
        self.result: dict[str, Any] | None = None
        self.state: Any = None
        self.body_executed = False
        self.body_completed_normally = False
        self.history_index: int | None = None
        self.result_message: ToolResultMessage | None = None
        self.history_updated = False

    def mark_history_updated(self) -> None:
        """Record a structural History change only after its required save succeeds."""
        self.history_updated = True


class BaseTool(ABC):
    """An invocation-independent tool definition with optional lifecycle phases."""

    def __init__(
        self,
        *,
        name: str,
        toolset: str,
        schema: dict[str, Any],
        is_async: bool = False,
        description: str = "",
        max_result_size_chars: int | None = None,
        dynamic_schema_overrides: Callable[[], dict[str, Any]] | None = None,
        danger_level: ToolDangerLevel = ToolDangerLevel.safe,
        no_timeout: bool = False,
        availability: ToolAvailability = ToolAvailability.EVERY,
        resets_turn_counter: bool = False,
        accepts_following_calls: bool = True,
        check_fn: Callable[[], bool] | None = None,
        requires_env: tuple[str, ...] = (),
    ) -> None:
        self.name = name
        self.toolset = toolset
        self.schema = schema
        self.is_async = is_async
        self.description = description or str(schema.get("description", ""))
        self.max_result_size_chars = max_result_size_chars
        self.dynamic_schema_overrides = dynamic_schema_overrides
        self.danger_level = danger_level
        self.no_timeout = no_timeout
        self.availability = availability
        self.resets_turn_counter = resets_turn_counter
        self.accepts_following_calls = accepts_following_calls
        self.check_fn = check_fn
        self.requires_env = tuple(requires_env)

    def ensure_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Copy arguments; concrete tools may perform pure validation here."""
        return dict(arguments)

    def before_handle(self, execution: ToolExecution) -> None | Awaitable[None]:
        """Prepare an approved call. The default phase has no side effects."""
        return None

    @abstractmethod
    def handle(self, execution: ToolExecution) -> ToolHandlerResult | Awaitable[ToolHandlerResult]:
        """Perform the tool operation."""
        raise NotImplementedError

    def after_handle(self, execution: ToolExecution) -> ToolPostprocessEffect | Awaitable[ToolPostprocessEffect]:
        """Run only after a normally returned body result is committed."""
        return ToolPostprocessEffect()


class BaseToolSet:
    """Toolset metadata and immutable declaration snapshot, not a second index."""

    def __init__(
        self,
        *,
        name: str,
        tools: tuple[BaseTool, ...] = (),
        description: str = "",
        usage_guide: str = "",
        loaded_by_default: bool = False,
        check_fn: Callable[[], bool] | None = None,
        requires_env: tuple[str, ...] = (),
    ) -> None:
        self.name = name
        self.tools = tuple(tools)
        self.description = description
        self.usage_guide = usage_guide
        self.loaded_by_default = loaded_by_default
        self.check_fn = check_fn
        self.requires_env = tuple(requires_env)
        for tool in self.tools:
            if tool.toolset != name:
                raise ValueError(f"Tool {tool.name!r} belongs to {tool.toolset!r}, not {name!r}")

    def preheat(self) -> bool:
        """Check registration availability without starting heavyweight resources."""
        return True


def tool_result(data: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    """Build a normal tool result payload."""
    return data if data is not None else kwargs


def tool_error(message: str, **extra: Any) -> dict[str, Any]:
    """Build an explicit business rejection payload."""
    return {"error": str(message), **extra}
