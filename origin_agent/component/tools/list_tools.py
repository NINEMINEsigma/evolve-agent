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
        from subagent.report_tool import current_subagent_loop
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
        # 按危险等级过滤并返回当前注册表中匹配的工具名称列表。
        "description": (
            "Return a sorted list of names for currently registered tools filtered by danger level. "
            "Accepted levels: 'readonly', 'write', 'dangerous'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "danger_level": {
                    "type": "string",
                    # 要过滤的危险等级。可选值：readonly、write、dangerous。
                    "description": "Danger level to filter by. One of: 'readonly', 'write', 'dangerous'.",
                },
            },
            "required": ["danger_level"],
        },
    },
    handler=_handle_list_tools,
    emoji="🧰",
    danger_level="readonly",
)