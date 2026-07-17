"""运行子 Agent。

模块导入时通过 ``registry.register()`` 注册 ``run_subagent`` 工具。
通过已注册的子 Agent 配置启动一次子 Agent 会话。
"""

from __future__ import annotations

from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result
from entity.puretype import ToolAvailability, ToolDangerLevel
from system.context import get_runtime_context
from system.sandbox import Sandbox

from ._store import SubagentStore


async def _handle_run_subagent(args: dict[str, Any]) -> dict:
    """启动子 Agent 会话。

    预期参数：
        name:            str       — 已注册子 Agent 的名称
        temperature:     float     — 采样温度（默认 1.0，范围 0.0–1.3）
        initial_prompt:  str       — 发送给子 Agent 的初始提问词
        user_name:       str       — 本轮发送者身份名称（必填）
        message_type:    str       — "direct" 或 "overheard"（必填）
    """
    name: str = str(args.get("name", "")).strip()
    initial_prompt: str = str(args.get("initial_prompt", "")).strip()
    user_name: str = str(args.get("user_name", "")).strip()
    message_type: str = str(args.get("message_type", "")).strip().lower()
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

    if not name:
        return tool_error("'name' is required and must not be empty")
    if not initial_prompt:
        return tool_error("'initial_prompt' is required and must not be empty")
    if not user_name:
        return tool_error("'user_name' is required and must not be empty")
    if message_type not in ("direct", "overheard"):
        return tool_error("'message_type' must be 'direct' or 'overheard'")

    store = SubagentStore(get_runtime_context().agentspace)
    profile = store.get(name)
    if profile is None:
        return tool_error(
            f"Subagent '{name}' not found. "
            "The registry may be corrupted; please re-register."
        )

    # 校验 system_prompt_paths
    system_prompt_paths = profile.system_prompt_paths
    for p in system_prompt_paths:
        if not isinstance(p, str):
            return tool_error("'system_prompt_paths' must be a list of strings")
    if len(system_prompt_paths) != len(set(system_prompt_paths)):
        return tool_error("Duplicate paths found in 'system_prompt_paths'")
    sandbox = Sandbox(get_runtime_context())
    for p in system_prompt_paths:
        if not sandbox.exists(p):
            return tool_error(f"System prompt file not found: {p}")

    # 校验 history_path（若提供）：必须由沙箱解析且文件真实存在
    resolved_history_path: str | None = None
    if history_path:
        try:
            resolved = sandbox.resolve_read(history_path)
        except Exception as exc:
            return tool_error(f"Invalid history_path: {exc}")
        if not resolved.real.exists():
            return tool_error(f"history_path not found: {history_path}")
        resolved_history_path = str(resolved.real)

    # 通过编排器启动子 Agent
    try:
        from system.application import Application
        orch = Application.current().subagent_orchestrator
        result = await orch.launch(
            parent_session_id=parent_session_id,
            name=name,
            profile=profile,
            temperature=temperature,
            initial_prompt=initial_prompt,
            user_name=user_name,
            message_type=message_type,
            history_path=resolved_history_path,
        )
        return tool_result(**result)
    except Exception as exc:
        return tool_error(f"Failed to launch subagent: {exc}")


registry.register(
    name="run_subagent",
    toolset="multiagent",
    schema={
        # 启动一个已注册子 Agent 的会话。
        #
        # ## 前置条件
        # 调用前必须先调用 list_subagents 确认目标子 Agent 已注册存在；不存在时必须先注册。
        # 必须明确决定是否传递 history_path：
        # - 不传递时，子 Agent 没有之前对话的记忆，只有人设/系统提示。
        # - 角色扮演型子 Agent 通常需要记忆，应传入由 stop_subagent 保存的 JSONL 历史文件。
        # - 功能型子 Agent 是否继承记忆需根据具体任务决定：若任务需要延续之前会话的上下文则传递；若只需要独立执行则不应传递。
        # 'initial_prompt' 参数就是发送给子 Agent 的首条消息，不要仅为了发送初始提示而再次调用 chat_subagent。
        #
        # ## 调用效果
        # 每次调用创建一个全新会话；若不传 history_path，子 Agent 不记得之前会话的任何内容，因此必须在 initial_prompt 中包含全部必要上下文。
        # 如需恢复之前会话，可传入 stop_subagent 保存的 JSONL 文件路径作为 history_path（沙箱逻辑路径，如 ws:subagents/name/session.jsonl）。
        # 子 Agent 默认拥有所有非 multiagent 工具，与父 Agent 同等权限（但无法创建子 Agent）。
        # temperature 被钳制在 0.0–1.3 之间。
        # 若活跃子 Agent 达到上限，新会话进入 FIFO 等待队列。
        # 同一主会话下同一 name 的子 Agent 只能有一个活跃或排队实例；若已存在，调用会失败，需先 stop_subagent 再重新 run。
        #
        # ## 返回
        # ```json
        # {"session_id": "...", "waiting": false, "queue_position": 0, "message": "..."}
        # ```
        # 队列中：{"session_id": "...", "waiting": true, "queue_position": 1, "message": "..."}
        #
        # ## 何时使用
        # - 将复杂任务拆分给专门子 Agent 执行。
        # - 需要子 Agent 在隔离上下文中处理子任务。
        # - 需要恢复之前停止的子 Agent 会话（传入 history_path）。
        # - 需要让角色扮演型子 Agent 保持连续记忆时（传入 history_path）。
        # - 需要功能型子 Agent 独立执行、避免历史干扰时（不传 history_path）。
        #
        # ## 副作用/注意
        # - 子 Agent 默认拥有所有非 multiagent 工具，可能执行 write / dangerous 工具，产生与父 Agent 同等的实际影响。
        # - 同一 name 的注册配置全局共享。
        # - 是否继承历史必须显式决定；默认不传 history_path 即无记忆。
        "description": """Start a session with a registered sub-agent.

## Prerequisites
Before calling this tool, call list_subagents to confirm the target sub-agent is registered; if it is not registered, register it first.
You MUST explicitly decide whether to pass history_path:
- Without history_path, the sub-agent has no memory of previous conversations; only its persona/system prompt remains.
- Role-play sub-agents usually need memory, so pass the JSONL history file saved by stop_subagent.
- Functional sub-agents may or may not need memory depending on the task: pass history_path only if the task requires continuing from a previous session's context; omit it for independent execution.
The 'initial_prompt' parameter IS the first message sent to the sub-agent — do NOT call chat_subagent separately just to send the initial prompt.

## Effect
Each call creates a brand-new session. If history_path is omitted, the sub-agent has NO memory of prior conversations, so you MUST include all necessary context in initial_prompt.
To resume a previous session, pass the sandbox logical path of the JSONL history file saved by stop_subagent as history_path (e.g. ws:subagents/name/session.jsonl). The path is resolved and validated; the tool call fails if the file does not exist.

The sub-agent has access to all non-multiagent tools (read, write, and dangerous) — the same tool set as the parent agent, minus recursive sub-agent creation.

temperature is clamped to the range 0.0–1.3.
If the active sub-agent limit is reached, the new session enters a FIFO waiting queue.
Within the same parent session, only one instance of a given sub-agent name can be active or queued at a time. If one already exists, the call fails; stop it first with stop_subagent before re-running it.

## Returns
```json
{"session_id": "...", "waiting": false, "queue_position": 0, "message": "..."}
```
When queued:
```json
{"session_id": "...", "waiting": true, "queue_position": 1, "message": "..."}
```

## When to Use
- Delegate a complex task to a specialized sub-agent.
- Run a sub-task in an isolated context.
- Resume a previously stopped sub-agent session (pass history_path).
- Keep a role-play sub-agent's continuous memory (pass history_path).
- Let a functional sub-agent execute independently without historical interference (omit history_path).

## Side Effects / Notes
- The sub-agent has access to all non-multiagent tools and may execute write/dangerous tools, causing real effects comparable to the parent agent.
- The registered profile is global and shared by all callers.
- Whether to inherit history must be decided explicitly; omitting history_path means no memory by default.
- Within the same parent session, only one instance of a given sub-agent name can be active or queued at a time.""",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    # 要运行的已注册子 Agent 的唯一名称。
                    "description": "Unique name of the registered sub-agent to run.",
                },
                "temperature": {
                    "type": "number",
                    # 子 Agent 的采样温度。默认 1.0，会被钳制到 0.0–1.3。
                    "description": "Sampling temperature for the sub-agent. Default 1.0, clamped to 0.0–1.3.",
                    "default": 1.0,
                },
                "initial_prompt": {
                    "type": "string",
                    # 发送给子 Agent 的首条消息（任务描述与完整上下文）。不要仅为了发送这条消息而再次调用 chat_subagent。
                    "description": """The first message (task description and full context) sent to the sub-agent. Do NOT call chat_subagent afterward just to send this prompt.""",
                },
                "user_name": {
                    "type": "string",
                    # 本轮消息的真实发送者名称（必填）。子 Agent 会根据此名称识别当前说话人。
                    "description": "The real sender's name for this turn (required). The sub-agent uses this to identify who is speaking to it.",
                },
                "message_type": {
                    "type": "string",
                    # 消息类型："direct" 表示直接对子 Agent 说，子 Agent 应响应；"overheard" 表示旁听，不必主动响应。
                    "description": "Message type: 'direct' means addressed to the sub-agent (it should respond); 'overheard' means the sub-agent is only listening in.",
                },
                "history_path": {
                    "type": "string",
                    # 可选。stop_subagent 保存的 JSONL 历史文件路径（沙箱逻辑路径，如 ws:subagents/name/session.jsonl）。工具会解析并校验存在性，不存在则调用失败。
                    "description": "Optional sandbox logical path to a JSONL history file saved by stop_subagent (e.g. ws:subagents/name/session.jsonl). The path is resolved and validated; the tool call fails if the file does not exist.",
                },
            },
            "required": ["name", "initial_prompt", "user_name", "message_type"],
        },
    },
    handler=_handle_run_subagent,
    is_async=True,
    emoji="🚀",
    danger_level=ToolDangerLevel.readonly,
    availability=ToolAvailability.MAIN,
)