"""启动一次性临时Agent。

模块导入时通过 ``registry.register()`` 注册 ``RunTaskAgent`` 工具。
父主会话通过此工具以单个 prompt 启动异步临时Agent，结果通过
``[subagent-result]`` 消息推送。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from abstract.tools.registry import registry, tool_error, tool_result
from entity.puretype import ToolAvailability, ToolDangerLevel

if TYPE_CHECKING:
    from entry.base_agent_loop import ToolContext


async def _handle_run_taskagent(
    args: dict[str, Any],
    context: ToolContext | None = None,
) -> dict:
    """使用调用时活动 LLM Profile 的快照启动一次性临时Agent。"""
    prompt: str = str(args.get("prompt", "")).strip()
    parent_session_id: str = str(args.get("_session_id", "")).strip()

    if not prompt:
        return tool_error("'prompt' is required and must not be empty")
    if not parent_session_id:
        return tool_error("'_session_id' is required and must not be empty")
    if context is None:
        return tool_error("RunTaskAgent requires an injected tool context")
    if context.llm_profile is None:
        return tool_error(
            "The parent main session has no active LLM Profile to inherit"
        )

    try:
        from system.application import Application

        app = Application.current()
        profile_snapshot = app.llm_profile_store.snapshot_profile(
            context.llm_profile
        )
        orch = app.subagent_orchestrator
        result = await orch.launch_taskagent(
            parent_session_id=parent_session_id,
            prompt=prompt,
            profile=profile_snapshot,
        )
        return tool_result(**result)
    except Exception as exc:
        return tool_error(f"Failed to launch taskagent: {exc}")


registry.register(
    name="RunTaskAgent",
    toolset="multiagent",
    schema={
        # 启动一个一次性临时Agent。
        # 临时Agent继承调用发生时父主会话的活动 LLM Profile快照，只携带一次任务消息。
        # 它只能调用已加载工具集中同时标记为 TASKAGENT 且危险等级为 safe 的工具。
        # 符合相同权限约束的 LoadToolset 可加载更多工具集，但不会扩大授权范围。
        # 结果通过 [subagent-result] 消息异步推送；不要轮询或尝试与临时Agent交互。
        # 如需提前终止，使用 StopTaskAgent 并传入返回的 session_id。
        "description": """Launch a one-shot task agent with a single prompt.

The task agent runs asynchronously and inherits a snapshot of the parent main session's active LLM Profile at call time. The caller cannot select a separate model or sampling temperature.

The task agent can only use tools from its loaded toolsets whose availability includes TASKAGENT and whose danger level is safe. It may use LoadToolset when that tool is available to load additional toolsets, but newly loaded tools remain subject to the same TASKAGENT-and-safe intersection.

The result is delivered as a [subagent-result] message when the task completes. Do not poll or interact with task agents. To terminate one early, use StopTaskAgent with the returned session_id.

## Effect
Creates a brand-new task agent session that executes the given prompt asynchronously. The task agent terminates automatically when the LLM produces a plain text reply with no tool calls. There is no registration, persistence, or history saving. If the active sub-agent limit is reached, the call fails.

## Returns
```json
{"success": true, "session_id": "...", "waiting": false}
```
On failure:
```json
{"success": false, "error": "..."}
```

## When to Use
- Execute a stateless pipeline or temporary task that can finish with safe tools and a text result.
- Isolate a read-oriented sub-task from the main Agent's conversation history.
- Avoid multi-round interaction or persistent memory.

## Side Effects / Notes
- Put all required context in `prompt`; this is the task agent's only task message.
- Loading a toolset does not authorize tools outside the TASKAGENT-and-safe intersection.
- The task agent does not save history and cannot be resumed.""",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    # 发送给临时Agent的唯一任务消息，必须包含全部必要上下文。
                    "description": "The complete task description and context. This is the only task message sent to the task agent.",
                },
            },
            "required": ["prompt"],
        },
    },
    handler=_handle_run_taskagent,
    is_async=True,
    danger_level=ToolDangerLevel.safe,
    availability=ToolAvailability.MAIN,
)
