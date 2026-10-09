"""工具注册、显式声明发现与 framework 生命周期入口。"""

from .registry import ToolRegistry, ToolEntry, ToolsetEntry, tool_error, tool_result
from .discover import ToolDiscoverySystem, discover_builtin_tools
