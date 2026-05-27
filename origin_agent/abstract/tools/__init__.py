"""抽象工具 — 自动发现工具注册表。

无外部依赖。纯 Python stdlib。
"""

from .registry import ToolRegistry, ToolEntry, tool_error, tool_result, registry
from .discover import discover_builtin_tools