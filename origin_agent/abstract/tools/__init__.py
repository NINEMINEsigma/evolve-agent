"""Hermes Tools — auto-discovery tool registry.

No external dependencies. Pure Python stdlib.
"""

from .registry import ToolRegistry, ToolEntry, tool_error, tool_result, registry
from .discover import discover_builtin_tools
