"""运行子 Agent。

模块导入时通过 ``registry.register()`` 注册 ``run_subagent`` 工具。
通过已注册的子 Agent 配置启动一次子 Agent 会话。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result


async def _handle_run_subagent(args: dict[str, Any]) -> dict:
    """启动子 Agent 会话。

    预期参数：
        name:            str       — 已注册子 Agent 的名称
        temperature:     float     — 采样温度（默认 1.0，范围 0.0–1.3）
        authorized_tools: list[str] | None — 额外授权的 write / dangerous 工具名称列表
        initial_prompt:  str       — 发送给子 Agent 的初始提问词
    """
    name: str = str(args.get("name", "")).strip()
    initial_prompt: str = str(args.get("initial_prompt", "")).strip()
    parent_session_id: str = str(args.get("_session_id", "")).strip()
    history_path: str = str(args.get("history_path", "")).strip()

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

    # 校验 authorized_tools：不允许 readonly，不允许 multiagent，工具必须存在
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
    if nonexist_authorized_tools:
        return tool_error(f"Tools: ['{', '.join(nonexist_authorized_tools)}'] do not exist in the registry.")
    if multiagent_authorized_tools:
        return tool_error(
            f"Tools: ['{', '.join(multiagent_authorized_tools)}'] belong to multiagent toolset "
            "and cannot be authorized for a sub-agent (recursive sub-agents are not allowed)."
        )

    # 校验 system_prompt_path（若指定则文件必须存在）
    system_prompt_path: str | None = profile.get("system_prompt_path")
    if system_prompt_path:
        if not Path(system_prompt_path).exists():
            return tool_error(f"System prompt file not found: {system_prompt_path}")

    # 通过编排器启动子 Agent
    profile["_name"] = name  # 注入注册名供编排器推送 WS 时使用
    try:
        from gateway.server import get_subagent_orchestrator
        orch = get_subagent_orchestrator()
        result = await orch.launch(
            profile=profile,
            temperature=temperature,
            authorized_tools=authorized_tools,
            initial_prompt=initial_prompt,
            parent_session_id=parent_session_id,
            history_path=history_path or None,
        )
        return tool_result(**result)
    except Exception as exc:
        return tool_error(f"Failed to launch subagent: {exc}")


registry.register(
    name="run_subagent",
    toolset="multiagent",
    schema={
        # 启动一个已注册子 Agent 的会话，传入初始提问词并返回会话 ID 和等待状态。
        # initial_prompt 即为发送给子 Agent 的首条消息，启动后无需再调用 chat_subagent 发送初始消息。
        # authorized_tools 仅用于额外授权 write / dangerous 工具，readonly 工具由系统预设决定。
        # temperature 取值范围被钳制在 0.0–1.3 之间。
        # 若活跃数达到上限则进入等待队列，返回值包含 waiting 和 queue_position。
        # 重要：每次启动都是全新会话，子 Agent 没有过往对话记忆。不要假设它知道之前发生过什么。
        # 必须把任务所需的所有上下文都写在 initial_prompt 里。
        # history_path 可用于恢复之前保存的子会话历史（stop_subagent 保存的 JSONL），
        # 传入后子 Agent 将在已有历史基础上继续，而非从零开始。
        "description": (
            "Start a session with a registered sub-agent. The 'initial_prompt' parameter "
            "IS the first message sent to the sub-agent — do NOT call chat_subagent "
            "separately just to send the initial prompt. "
            "Returns the session ID and waiting status.\n\n"
            "IMPORTANT: Each launch creates a brand-new session with NO memory of previous "
            "conversations. The sub-agent does NOT remember anything from prior sessions. "
            "You MUST include ALL necessary context in the initial_prompt.\n\n"
            "TO RESUME a previous sub-agent session: pass 'history_path' pointing to the "
            "JSONL file saved by stop_subagent. The sub-agent will continue from where "
            "it left off instead of starting fresh. Use this to split long tasks across "
            "multiple sub-agent sessions.\n\n"
            "TOOL ISOLATION — The sub-agent does NOT have the same tools as you:\n"
            "- Pre-authorized readonly tools (always available): "
            "list_tools, list_uploads, read_file, probe_vision_capability, read_image, read_csv, read_docx, "
            "read_excel, read_pdf, list_directory, search_files, grep, web_fetch, "
            "web_search, media_info.\n"
            "- No other tools are available by default — not even write_file or edit_file.\n"
            "- Tools CANNOT be changed after launch. If the task requires writing, editing, "
            "searching with grep, running commands, or any tool beyond those listed above, "
            "you MUST include those tool names in 'authorized_tools' at launch time.\n"
            "- Use 'list_tools' with danger_level='write' or 'dangerous' to see available "
            "tools, then decide which ones the sub-agent needs.\n\n"
            "Read-only tools are pre-authorized by the system (not all are granted). "
            "Use authorized_tools to explicitly grant access to write-level or dangerous tools. "
            "Read-only tools cannot be added or removed via authorized_tools.\n\n"
            "The temperature parameter is clamped to the range 0.0–1.3.\n\n"
            "If the active sub-agent limit is reached, the session enters a FIFO waiting queue. "
            "The return value includes 'waiting: true' and 'queue_position'."
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
                    # 发送给子 Agent 的首条消息（也是任务描述）。启动后无需再调用 chat_subagent 发送初始消息。
                    "description": "The initial prompt (task description) sent to the sub-agent. This IS the first message — do NOT call chat_subagent afterward just to send the initial prompt.",
                },
                "history_path": {
                    "type": "string",
                    # 可选：之前 stop_subagent 保存的 JSONL 文件路径，传入后子 Agent 在已有历史基础上继续。
                    "description": "Optional path to a previously saved sub-agent session JSONL (from stop_subagent). When provided, the sub-agent resumes from that history instead of starting fresh.",
                },
            },
            "required": ["name", "initial_prompt"],
        },
    },
    handler=_handle_run_subagent,
    is_async=True,
    emoji="🚀",
    danger_level="dangerous",
)