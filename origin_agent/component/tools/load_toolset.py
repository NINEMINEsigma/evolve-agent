"""LoadToolset — 按需加载工具集到当前会话。

显式注册协议：模块导出 ``register_tools(registry, ui_events)`` 注册工具。
属于 core 工具集，始终对当前 Loop 可见（availability=EVERY）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from abstract.tools.registry import ToolRegistry, tool_error, tool_result
from abstract.tools.ui_event_router import UIEventRouter
from entity.puretype import ToolAvailability, ToolDangerLevel

if TYPE_CHECKING:
    from entry.base_agent_loop import ToolContext


def _get_registry():
    """运行期取得唯一 ToolRegistry System 实例。"""
    from system.application import Application
    from abstract.tools.registry import ToolRegistry
    return Application.current().get_system(ToolRegistry)


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

    tool_registry = _get_registry()
    results: dict[str, Any] = {}
    loaded: list[str] = []

    for raw in names:
        name: str = str(raw).strip()
        if not name:
            results[name or "<empty>"] = {"loaded": False, "code": "empty_name", "error": "Toolset name must not be empty."}
            continue

        # 检查工具集是否已注册
        ts_entry = tool_registry.get_toolset_entry(name)
        if ts_entry is None and name not in tool_registry.get_registered_toolset_names():
            results[name] = {"loaded": False, "code": "unknown_toolset", "error": f"Unknown toolset: {name}"}
            continue

        # 加载工具集（幂等）
        newly = loop.load_toolsets([name])
        tool_names = tool_registry.get_tool_names_for_toolset(name)
        results[name] = {
            "loaded": True,
            "tools": tool_names,
            "already_loaded": name not in newly,
        }
        loaded.append(name)

    return tool_result(loaded=loaded, results=results)


def _build_load_toolset_description(registry: ToolRegistry) -> str:
    """构建 LoadToolset 的描述，包含当前已注册的工具集名称列表。"""
    base = """Load toolsets into the current session so their tools become available in subsequent LLM requests.

## Prerequisites
None. This tool is always available.

## Effect
Adds the named toolsets to the session's loaded set. Loading a toolset does not grant permission by itself: tools appear in the next LLM request only if they also pass the current Loop's availability, danger-level, runtime-availability, and other authorization filters. Already-loaded toolsets are idempotent (no error).

## Returns
```json
{
  "loaded": ["filesystem", "shell"],
  "results": {
    "filesystem": {"loaded": true, "tools": ["Read", "Write", "PatchEdit", "Delete", "Copy", "Move", "SearchFiles", "Grep", "ListUploads"], "already_loaded": false},
    "shell": {"loaded": true, "tools": ["StartShell", "ReadShell", "WriteShell", "InterruptShell", "StopShell"], "already_loaded": false},
    "missing": {"loaded": false, "code": "unknown_toolset", "error": "Unknown toolset: missing"}
  }
}
```

## When to Use
- Before calling a tool that belongs to a toolset not yet loaded in this session.
- When you need to discover what tools a toolset provides.

## Note
The returned tool names are discovery information for all registered members of each toolset; they are not a guarantee that every listed tool is visible or callable in the current Loop. Full schemas become available in subsequent LLM requests only for tools that pass all current Loop filters. The ``core`` toolset is always loaded and cannot be unloaded."""

    # 动态追加当前已注册的工具集名称
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


# ── schema 常量 ─────────────────────────────────────────────

_LOAD_TOOLSET_SCHEMA_BASE = {
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
}


# ── 注册 ─────────────────────────────────────────────────────

def register_tools(registry: ToolRegistry, ui_events: UIEventRouter) -> None:
    """Register the LoadToolset tool with a dynamically built description."""
    del ui_events  # LoadToolset has no UI event handler
    registry.register(
        name="LoadToolset",
        toolset="core",
        schema={
            **_LOAD_TOOLSET_SCHEMA_BASE,
            "description": _build_load_toolset_description(registry),
        },
        handler=_handle_load_toolset,
        danger_level=ToolDangerLevel.safe,
        availability=ToolAvailability.EVERY,
    )
