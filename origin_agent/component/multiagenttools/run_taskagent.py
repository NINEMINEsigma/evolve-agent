"""启动一次性任务 Agent。

模块导入时通过 ``registry.register()`` 注册 ``run_taskagent`` 工具。
父 Agent 通过此工具以单个 prompt 启动一个异步执行的 taskagent，
结果通过周期收集器以 [subagent-result] 消息推送。
"""

from __future__ import annotations

from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result
from entity.puretype import ToolAvailability, ToolDangerLevel


async def _handle_run_taskagent(args: dict[str, Any]) -> dict:
    """启动一次性 taskagent。

    预期参数：
        prompt:       str   — 任务描述（必填）
        temperature:  float — 采样温度（默认 1.0，范围 0.0–1.3）
    """
    prompt: str = str(args.get("prompt", "")).strip()
    parent_session_id: str = str(args.get("_session_id", "")).strip()

    temperature: float = 1.0
    raw_temp = args.get("temperature")
    if raw_temp is not None:
        try:
            temperature = float(raw_temp)
            if temperature < 0.0 or temperature > 1.3:
                return tool_error("'temperature' must be between 0.0 and 1.3")
        except (ValueError, TypeError):
            return tool_error("'temperature' must be a valid number")

    if not prompt:
        return tool_error("'prompt' is required and must not be empty")
    if not parent_session_id:
        return tool_error("'_session_id' is required and must not be empty")

    try:
        from system.application import Application
        orch = Application.current().subagent_orchestrator
        result = await orch.launch_taskagent(
            parent_session_id=parent_session_id,
            prompt=prompt,
            temperature=temperature,
        )
        return tool_result(**result)
    except Exception as exc:
        return tool_error(f"Failed to launch taskagent: {exc}")


registry.register(
    name="run_taskagent",
    toolset="multiagent",
    schema={
        # 启动一个一次性任务 Agent (taskagent)。
        # taskagent 异步执行，只携带一次任务消息，只能使用 readonly 等级工具。
        # 结果通过 [subagent-result] 消息异步推送，不要轮询或尝试与 taskagent 交互。
        # 如需提前终止，使用 stop_taskagent 并传入返回的 session_id。
        #
        # ## 调用效果
        # 创建一个全新的 taskagent 会话，异步执行任务。
        # taskagent 完成后（LLM 产出纯文本回复）自动终止，结果通过周期收集器推送。
        # 无注册、无持久化、不保存历史。
        # 活跃子 Agent 达到上限时调用会失败。
        #
        # ## 返回
        # ```json
        # {"success": true, "session_id": "...", "waiting": false}
        # ```
        # 失败时：
        # ```json
        # {"success": false, "error": "..."}
        # ```
        #
        # ## 何时使用
        # - 需要执行流水线任务或临时任务。
        # - 需要在隔离上下文中以 readonly 工具执行子任务。
        # - 不需要与子 Agent 进行多轮交互。
        #
        # ## 副作用/注意
        # - taskagent 只能使用 readonly 等级工具，不会产生不可逆影响。
        # - 结果异步推送，有最多 20 秒延迟（取决于周期收集器触发时机）。
        # - 不保存会话历史，无法恢复。
        "description": """Launch a one-shot task agent with a single prompt.

The task agent runs asynchronously with readonly tools only. The result is delivered as a [subagent-result] message when the task completes. Do not poll or interact with task agents — they are fire-and-forget.

To terminate a task agent early, use stop_taskagent with the returned session_id.

## Effect
Creates a brand-new task agent session that executes the given prompt asynchronously. The task agent terminates automatically when the LLM produces a plain text reply (no tool calls). No registration, no persistence, no history saving.

If the active sub-agent limit is reached, the call fails.

## Returns
```json
{"success": true, "session_id": "...", "waiting": false}
```
On failure:
```json
{"success": false, "error": "..."}
```

## When to Use
- Execute a pipeline task or a temporary task.
- Run a sub-task in an isolated context with readonly tools.
- When multi-round interaction with a sub-agent is not needed.

## Side Effects / Notes
- The task agent can only use readonly-level tools; it cannot cause irreversible effects.
- Results are delivered asynchronously with up to ~20 seconds delay (depending on the cycle collector trigger).
- No session history is saved; the task agent cannot be resumed.""",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    # 任务描述与完整上下文。这是发送给 taskagent 的唯一消息，需包含全部必要信息。
                    "description": "The task description and full context. This is the only message sent to the task agent; include all necessary information.",
                },
                "temperature": {
                    "type": "number",
                    # 采样温度。默认 1.0，会被钳制到 0.0–1.3。
                    "description": "Sampling temperature. Default 1.0, clamped to 0.0–1.3.",
                    "default": 1.0,
                },
            },
            "required": ["prompt"],
        },
    },
    handler=_handle_run_taskagent,
    is_async=True,
    emoji="📋",
    danger_level=ToolDangerLevel.readonly,
    availability=ToolAvailability.MAIN,
)