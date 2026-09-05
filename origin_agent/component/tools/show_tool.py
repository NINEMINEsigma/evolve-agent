"""ShowTool 工具 — 查询当前会话可见工具/工具集的元数据。

按 ``names`` 列表查询，每个名称先按工具匹配（返回 no_timeout / is_async /
danger_level / toolset 四字段），未命中再按工具集匹配（返回该 toolset 下
可见工具名列表）。仅返回当前 loop 上下文下实际可调用的工具，不可见或不
存在的名称按单条 error 返回，不阻塞其余项。

模块导入时通过 ``registry.register()`` 注册 ``ShowTool`` 工具。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from abstract.tools.registry import registry, tool_error, tool_result
from entity.puretype import ToolAvailability, ToolDangerLevel
from entity.constant import COLLOQUY_TOOLSET_WHITELIST

if TYPE_CHECKING:
    from entry.base_agent_loop import ToolContext


# ---------------------------------------------------------------------------
# 可见性辅助
# ---------------------------------------------------------------------------

def _names_for_availability(scope: ToolAvailability) -> set[str]:
    """按 availability scope 求可见工具名集合。

    复用 ``get_definitions_for_availability``，其内部已叠加 ``check_fn``
    可用性过滤（30 秒 TTL 缓存）。
    """
    defs = registry.get_definitions_for_availability(scope, quiet=True)
    return {(d.get("function") or {}).get("name", "") for d in defs} - {""}


def _visible_tool_names(context: ToolContext | None) -> set[str]:
    """按当前 loop 类型分派，返回该 loop 上下文下可见的工具名集合。

    使用 ``isinstance`` 类型分派（非反射），判定顺序先子后父：
    ``SubAgentLoop``（含 ``TaskAgentLoop``）→ ``ColloquyLoop`` →
    ``MultiAgentLoop`` → 兜底（``ParentAgentLoop`` 等）。
    """
    loop = context.loop if context is not None else None
    if loop is None:
        return _names_for_availability(ToolAvailability.MAIN)

    # 延迟导入避免 component → entry/subagent 模块级循环依赖
    from subagent.loop import SubAgentLoop
    from entry.colloquy_loop import ColloquyLoop
    from entry.multi_agent_loop import MultiAgentLoop

    if isinstance(loop, SubAgentLoop):
        # 含 TaskAgentLoop（其 allowed_tool_names 构造时已按 scope+safe 过滤）
        return {n for n in loop.allowed_tool_names if registry.is_tool_available(n)}
    if isinstance(loop, ColloquyLoop):
        # 白名单 toolset 内的工具名 ∩ MAIN 可见集合
        whitelist: set[str] = {
            n for n, ts in registry.get_tool_to_toolset_map().items()
            if ts in COLLOQUY_TOOLSET_WHITELIST
        }
        return _names_for_availability(ToolAvailability.MAIN) & whitelist
    if isinstance(loop, MultiAgentLoop):
        return _names_for_availability(ToolAvailability.MULTI_AGENT)
    # 兜底：ParentAgentLoop 及其他
    return _names_for_availability(ToolAvailability.MAIN)


# ---------------------------------------------------------------------------
# handler
# ---------------------------------------------------------------------------

def _handle_show_tool(args: dict[str, Any], context: ToolContext | None = None) -> dict:
    """查询 ``names`` 列表中工具/工具集的元数据。

    对每个名称：先按工具匹配（返回四字段元数据），未命中按工具集匹配
    （返回可见工具名列表），均未命中返回单条 error。不泄露不可见工具/
    工具集的存在性。
    """
    names = args.get("names")
    if not isinstance(names, list) or not names:
        return tool_error("'names' must be a non-empty list of tool or toolset names")

    visible: set[str] = _visible_tool_names(context)
    results: dict[str, Any] = {}

    for raw in names:
        name: str = str(raw).strip()
        # 先按工具匹配
        entry = registry.get_entry(name)
        if entry is not None and name in visible:
            results[name] = {
                "no_timeout": entry.no_timeout,
                "is_async": entry.is_async,
                "danger_level": entry.danger_level.value,
                "toolset": entry.toolset,
            }
            continue

        # 回落按工具集匹配（仅当该 toolset 下有可见工具时才返回，避免泄露存在性）
        if name in registry.get_registered_toolset_names():
            tools: list[str] = [
                n for n in registry.get_tool_names_for_toolset(name) if n in visible
            ]
            if tools:
                results[name] = {
                    "toolset": name,
                    "tools": tools,
                }
                continue

        # 未命中或不可见
        results[name] = {"error": f"unknown tool or toolset: {name}"}

    return tool_result(results=results)


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

registry.register(
    name="ShowTool",
    toolset="core",
    schema={
        # 查询当前会话可见的工具或工具集的元数据。
        # 对工具名返回 {no_timeout, is_async, danger_level, toolset}；
        # 对工具集名返回该 toolset 下可见工具名列表。
        # 仅返回当前 loop 上下文下实际可调用的工具，不可见/不存在的名称按单条 error 返回。
        # 前置条件：无。
        # 调用效果：无副作用，纯查询。
        # 返回格式：{ results: { <name>: <metadata dict | error dict>, ... } }
        # 典型场景：了解工具能力边界；排查工具可见性；查看工具集成员。
        # 注意：子 Agent / Colloquy / 多 Agent 等不同 loop 上下文下可见集不同。
        "description": """Show metadata for tools or toolsets visible in the current session.

Given a list of names, each name is resolved first as a tool (returning `{no_timeout, is_async, danger_level, toolset}`), then as a toolset (returning the list of visible tool names it contains). Only tools actually callable in the current loop context are reported; invisible or unknown names return a per-item error without blocking the rest.

## Prerequisites
None.

## Effect
No side effects, read-only query.

## Returns
```json
{
  "results": {
    "Read": { "no_timeout": false, "is_async": false, "danger_level": "safe", "toolset": "filesystem" },
    "core": { "toolset": "core", "tools": ["Ask", "ShowTool", ...] },
    "nope": { "error": "unknown tool or toolset: nope" }
  }
}
```

## When to Use
- Inspecting a tool's timeout / async / danger / toolset metadata.
- Listing the visible members of a toolset.
- Diagnosing why a tool is or is not available in the current context.

## Note
The visible set depends on the current loop type (parent / sub-agent / colloquy / multi-agent). A name that is registered but not visible in the current context is treated as unknown — its existence is not leaked.""",
        "parameters": {
            "type": "object",
            "properties": {
                "names": {
                    "type": "array",
                    "items": {"type": "string"},
                    # 要查询的名称列表，元素可为工具名或工具集名。
                    "description": "List of names to query. Each element may be a tool name or a toolset name.",
                },
            },
            "required": ["names"],
        },
    },
    handler=_handle_show_tool,
    danger_level=ToolDangerLevel.safe,
)