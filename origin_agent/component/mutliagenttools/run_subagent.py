"""运行子 Agent。

模块导入时通过 ``registry.register()`` 注册 ``run_subagent`` 工具。
通过已注册的子 Agent 配置启动一次子 Agent 会话，并返回其回复。
"""

from __future__ import annotations

from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result


def _handle_run_subagent(args: dict[str, Any]) -> dict:
    """启动子 Agent 会话并返回其回复。

    预期参数：
        name:          str       — 已注册子 Agent 的名称
        temperature:   float     — 采样温度（默认 1.0，范围 0.0–1.3）
        authorized_tools: list[str] | None — 额外授权的 write / dangerous 工具名称列表
        initial_prompt: str    — 发送给子 Agent 的初始提问词

    工具授权规则：
      - readonly 工具由系统预设决定是否授权，不在 authorized_tools 中配置；
      - authorized_tools 仅用于额外授权 write / dangerous 工具，不允许传入 readonly 工具；
      - 未被系统预设授权的 readonly 工具（如 ask_question）不会被使用。
    """
    name: str = str(args.get("name", "")).strip()
    initial_prompt: str = str(args.get("initial_prompt", "")).strip()
    temperature: float = 1.0
    raw_temp = args.get("temperature")
    if raw_temp is not None:
        try:
            temperature = float(raw_temp)
            if temperature < 0.0 or temperature > 1.3:
                return tool_error("'temperature' must be between 0.0 and 1.3")
        except (ValueError, TypeError):
            return tool_error("'temperature' must be a valid number")

    raw_authorized: Any = args.get("authorized_tools")
    authorized_tools: list[str] = []
    if raw_authorized is not None:
        if not isinstance(raw_authorized, list):
            return tool_error("'authorized_tools' must be a list of strings")
        authorized_tools = [str(t).strip() for t in raw_authorized if str(t).strip()]

    if not name:
        return tool_error("'name' is required and must not be empty")
    if not initial_prompt:
        return tool_error("'initial_prompt' is required and must not be empty")

    from ._store import _subagent_registry

    if name not in _subagent_registry:
        return tool_error(f"Subagent '{name}' not found. Register it first.")

    profile = _subagent_registry[name]

    nonexist_authorized_tools = []
    multiagent_authorized_tools = []
    for tool_name in authorized_tools:
        level = registry.get_danger_level(tool_name)
        if level == "readonly":
            return tool_error(
                f"Tool '{tool_name}' is read-only and cannot be added via authorized_tools."
            )
        entry = registry.get_entry(tool_name)
        if entry is None:
            nonexist_authorized_tools.append(tool_name)
        elif entry.toolset == "multiagent":
            multiagent_authorized_tools.append(tool_name)
    bad_message = ""
    if nonexist_authorized_tools:
        bad_message += f"Tools: ['{', '.join(nonexist_authorized_tools)}'] do not exist in the registry.\n"
    if multiagent_authorized_tools:
        bad_message += f"Tools: ['{', '.join(multiagent_authorized_tools)}'] belong to multiagent toolset and cannot be authorized for a sub-agent (recursive sub-agents are not allowed).\n"
    if bad_message:
        return tool_error(bad_message)

    # TODO: subagent 执行逻辑尚未实现，需求文档见 subagent.plan.md
    # 参数校验已完成，下一步实现子 Agent 会话的创建、周期收集、工具审批、停止等功能

    return tool_result(
        success=True,
        name=name,
        base_url=profile.get("base_url"),
        model=profile.get("model"),
        temperature=temperature,
        authorized_tools=authorized_tools,
        initial_prompt=initial_prompt,
        message="Parameters validated successfully. Execution not yet implemented.",
    )


registry.register(
    name="run_subagent",
    toolset="multiagent",
    schema={
        # 启动一个已注册子 Agent 的会话，传入初始提问词并返回其回复。
        # authorized_tools 仅用于额外授权 write / dangerous 工具，readonly 工具由系统预设决定。
        # temperature 取值范围被钳制在 0.0–1.3 之间。
        "description": (
            "Start a session with a registered sub-agent, send an initial prompt, "
            "and return its response.\n\n"
            "Read-only tools are pre-authorized by the system (not all are granted). "
            "Use authorized_tools to explicitly grant access to write-level or dangerous tools. "
            "Read-only tools cannot be added or removed via authorized_tools.\n\n"
            "The temperature parameter is clamped to the range 0.0–1.3."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    # 已注册子 Agent 的唯一标识名称。
                    "description": "Name of the registered sub-agent to run.",
                },
                "temperature": {
                    "type": "number",
                    # 采样温度，控制输出随机性，取值范围 0.0–1.3。
                    "description": "Sampling temperature for the sub-agent (default 1.0, clamped to 0.0–1.3).",
                    "default": 1.0,
                },
                "authorized_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    # 额外授权的 write / dangerous 工具名称列表，readonly 工具不允许传入。
                    "description": (
                        "List of write-level or dangerous tool names to explicitly authorize for the sub-agent. "
                        "Read-only tools are pre-authorized by the system and cannot be added or removed here."
                    ),
                },
                "initial_prompt": {
                    "type": "string",
                    # 发送给子 Agent 的初始提问词。
                    "description": "The initial prompt to send to the sub-agent.",
                },
            },
            "required": ["name", "initial_prompt"],
        },
    },
    handler=_handle_run_subagent,
    emoji="🚀",
    danger_level="dangerous",
)