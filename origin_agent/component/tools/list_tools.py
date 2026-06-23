"""按危险等级列出当前已注册工具。

模块导入时通过 ``registry.register()`` 注册 ``list_tools`` 工具。
"""

from __future__ import annotations

from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result


def _handle_list_tools(args: dict[str, Any]) -> dict:
    """返回当前注册表中指定危险等级的工具名称列表。

    在子 Agent 上下文中调用时，只返回该子 Agent 被授权的工具，
    避免子 Agent 看到全局清单后绕过沙箱。
    """
    danger_level: str = str(args.get("danger_level", "")).strip()

    valid_levels = {"readonly", "write", "dangerous"}
    if not danger_level:
        return tool_error("'danger_level' is required")
    if danger_level not in valid_levels:
        return tool_error(
            f"Invalid danger_level '{danger_level}'. Must be one of: {', '.join(sorted(valid_levels))}."
        )

    # 子 Agent 沙箱：仅暴露被授权的工具
    allowed: set[str] | None = None
    try:
        from subagent.loop import current_subagent_loop
        loop = current_subagent_loop.get()
        if loop is not None:
            allowed = loop.allowed_tool_names
    except (LookupError, ImportError):
        allowed = None

    names = [
        name
        for name in registry.get_all_tool_names()
        if registry.get_danger_level(name) == danger_level
        and (allowed is None or name in allowed)
    ]
    return tool_result(
        success=True,
        danger_level=danger_level,
        count=len(names),
        names=names,
    )


registry.register(
    name="list_tools",
    toolset="core",
    schema={
        # 列出当前 agent 可用的工具名称，按危险等级筛选。
        # 前置条件：无。
        # 调用效果：无副作用，纯查询。
        # 返回格式：{ success, danger_level, count, names: [...] }
        # 典型场景：排查工具可用性；了解当前权限边界。
        # 注意：在子 Agent 中调用时仅返回该子 Agent 被授权的工具名称，不暴露全局注册表。
        "description": """List currently available tool names filtered by danger level.

## Prerequisites
None.

## danger_level Meanings

| Level | Impact |
|-------|--------|
| `readonly` | Operations fully confined within the sandbox, no external system impact. |
| `write` | May have indirect impact (e.g. writing scripts that won't auto-execute but could contain high-risk code). |
| `dangerous` | Misuse can directly cause catastrophic damage to the entire machine or critical assets. |

## Effect
No side effects, read-only query.

## Returns
```json
{ "success": true, "danger_level": "<level>", "count": N, "names": ["tool_a", "tool_b", ...] }
```

## When to Use
- Diagnosing tool availability.
- Understanding current permission scope.

## Note
When called from a sub-agent, only tools authorized for that sub-agent are returned; the global registry is never exposed.""",
        "parameters": {
            "type": "object",
            "properties": {
                "danger_level": {
                    "type": "string",
                    # 要筛选的危险等级。
                    # 'readonly'=沙箱内操作无外部影响，'write'=可能间接影响，'dangerous'=可直接毁灭性打击。
                    "description": """Danger level to filter by.

- `readonly` — sandbox-confined, no external impact.
- `write` — may have indirect impact.
- `dangerous` — capable of catastrophic direct damage.""",
                },
            },
            "required": ["danger_level"],
        },
    },
    handler=_handle_list_tools,
    emoji="🧰",
    danger_level="readonly",
)