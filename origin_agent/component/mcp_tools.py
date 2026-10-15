"""MCP management tool objects discovered through the TOOLSET declaration."""

from __future__ import annotations

from abstract.tools.tool import BaseTool, BaseToolSet, ToolExecution, ToolHandlerResult
from entity.puretype import ToolAvailability, ToolDangerLevel

_MCP_REFRESH_SCHEMA = {
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
}


class MCPRefreshTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            name="MCPRefresh",
            toolset="mcp",
            schema=_MCP_REFRESH_SCHEMA,
            is_async=True,
            danger_level=ToolDangerLevel.safe,
            availability=ToolAvailability.MAIN,
        )

    async def handle(self, execution: ToolExecution) -> ToolHandlerResult:
        from abstract.mcp.system import MCPSystem

        return ToolHandlerResult(result=await execution.context.app.get_system(MCPSystem).refresh())


TOOLSET = BaseToolSet(name="mcp", tools=(MCPRefreshTool(),))
