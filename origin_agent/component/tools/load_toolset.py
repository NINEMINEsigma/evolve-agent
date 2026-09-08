"""LoadToolset — 按需加载工具集到当前会话。

模块导入时通过 ``registry.register()`` 注册。
属于 core 工具集，始终对当前 Loop 可见（availability=EVERY）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from abstract.tools.registry import registry, tool_error, tool_result
from entity.puretype import ToolAvailability, ToolDangerLevel

if TYPE_CHECKING:
    from entry.base_agent_loop import ToolContext


def _handle_load_toolset(args: dict[str, Any], context: ToolContext | None = None) -> dict:
    """批量加载工具集到当前会话。

    对每个名称：检查工具集是否存在，存在则加入会话已加载集合并持久化。
    返回逐项结果，不返回完整 schema。
    """
    names = args.get("names")
    if not isinstance(names, list) or not names:
        return tool_error("'names' must be a non-empty list of toolset names")

    loop = context.loop if context is not None else None
    if loop is None:
        return tool_error("No loop context available")

    results: dict[str, Any] = {}
    loaded: list[str] = []

    for raw in names:
        name: str = str(raw).strip()
        if not name:
            results[name or "<empty>"] = {"loaded": False, "code": "empty_name", "error": "Toolset name must not be empty."}
            continue

        # 检查工具集是否已注册
        ts_entry = registry.get_toolset_entry(name)
        if ts_entry is None and name not in registry.get_registered_toolset_names():
            results[name] = {"loaded": False, "code": "unknown_toolset", "error": f"Unknown toolset: {name}"}
            continue

        # 加载工具集（幂等）
        newly = loop.load_toolsets([name])
        tool_names = registry.get_tool_names_for_toolset(name)
        results[name] = {
            "loaded": True,
            "tools": tool_names,
            "already_loaded": name not in newly,
        }
        loaded.append(name)

    return tool_result(loaded=loaded, results=results)


def _build_load_toolset_description() -> str:
    """构建 LoadToolset 的描述，包含当前已注册的工具集名称列表。"""
    base = """Load toolsets into the current session so their tools become available in subsequent LLM requests.

## Prerequisites
None. This tool is always available.

## Effect
Adds the named toolsets to the session's loaded set. Tools from loaded toolsets will appear in the next LLM request's tool definitions. Already-loaded toolsets are idempotent (no error).

## Returns
```json
{
  "loaded": ["filesystem", "shell"],
  "results": {
    "filesystem": {"loaded": true, "tools": ["Read", "Write", "PatchEdit", "Delete", "Copy", "Move", "SearchFiles", "Grep", "ListUploads"], "already_loaded": false},
    "shell": {"loaded": true, "tools": ["RunCommand"], "already_loaded": false},
    "missing": {"loaded": false, "code": "unknown_toolset", "error": "Unknown toolset: missing"}
  }
}
```

## When to Use
- Before calling a tool that belongs to a toolset not yet loaded in this session.
- When you need to discover what tools a toolset provides.

## Note
The returned tool names are for discovery only; the full tool schemas will be available in subsequent LLM requests after loading. The ``core`` toolset is always loaded and cannot be unloaded."""

    # 动态追加当前已注册的工具集名称
    from abstract.tools.registry import registry
    catalog = registry.get_registered_toolset_names()
    if catalog:
        base += "\n\n## Available Toolsets\n"
        for name in catalog:
            ts_entry = registry.get_toolset_entry(name)
            desc = ts_entry.description if ts_entry else ""
            if desc:
                base += f"- {name}: {desc}\n"
            else:
                base += f"- {name}\n"

    return base


registry.register(
    name="LoadToolset",
    toolset="core",
    schema={
        "description": _build_load_toolset_description(),
        "parameters": {
            "type": "object",
            "properties": {
                "names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of toolset names to load. Each name must match a registered toolset.",
                },
            },
            "required": ["names"],
        },
    },
    handler=_handle_load_toolset,
    danger_level=ToolDangerLevel.safe,
    availability=ToolAvailability.EVERY,
)
