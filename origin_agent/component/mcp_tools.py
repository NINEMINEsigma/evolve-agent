"""MCP management tools registered through explicit discovery."""

from __future__ import annotations

from typing import Any

from abstract.tools.registry import ToolRegistry
from abstract.tools.ui_event_router import UIEventRouter
from entity.puretype import ToolAvailability, ToolDangerLevel


async def _handle_mcp_refresh(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """Refresh MCP servers through the owning system."""
    from abstract.mcp.system import MCPSystem
    from system.application import Application

    return await Application.current().get_system(MCPSystem).refresh()


def register_tools(registry: ToolRegistry, ui_events: UIEventRouter) -> None:
    """Register MCP management tools into explicit runtime registries."""
    del ui_events
    registry.register(
        name="MCPRefresh",
        toolset="mcp",
        schema={
            "description": """Hot-reload MCP server connections from the config file.

Re-reads ``mcp_config.json`` and applies a diff against the currently
connected servers:

- **Removed**: servers present in the config before but absent now (or
  explicitly ``enabled: false``) are shut down and their tools deregistered.
- **Added**: servers newly present in the config (including servers that
  failed to connect at startup) are connected and their tools registered.
- **Circuit breaker**: error counts are reset for all affected servers.

No parameters. Returns a JSON object with keys:
``refreshed`` (bool), ``removed`` (list), ``added`` (list),
``failed`` (list), ``status`` (list of server status dicts).

Use this after editing ``mcp_config.json`` to add, remove, or re-enable
MCP servers without restarting the agent.""",
            "parameters": {"type": "object", "properties": {}},
        },
        handler=_handle_mcp_refresh,
        is_async=True,
        danger_level=ToolDangerLevel.safe,
        availability=ToolAvailability.MAIN,
    )
