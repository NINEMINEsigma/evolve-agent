"""启动动态角色档案对应的子Agent会话。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result
from entity.puretype import ToolAvailability, ToolDangerLevel
from system.application import Application
from subagent.profile import CharacterProfileError, CharacterProfileResolver


async def _handle_run_subagent(args: dict[str, Any]) -> dict:
    """启动一个动态发现的角色子Agent会话。"""
    name: str = str(args.get("name", "")).strip()
    initial_prompt: str = str(args.get("initial_prompt", "")).strip()
    user_name: str = str(args.get("user_name", "")).strip()
    message_type: str = str(args.get("message_type", "")).strip().lower()
    parent_session_id: str = str(args.get("_session_id", "")).strip()

    raw_history_path = args.get("history_path")
    history_path = raw_history_path.strip() if isinstance(raw_history_path, str) else ""

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

    app = Application.current()
    resolver = CharacterProfileResolver(app.sandbox, app.llm_profile_store)
    try:
        profile = resolver.require(name)
    except CharacterProfileError as exc:
        return tool_error(str(exc), name=name, profile_available=False)

    resolved_history_path: str | None = None
    if history_path:
        if Path(history_path.split(":", 1)[-1]).suffix.lower() != ".es":
            return tool_error("history_path must point to an easysave .es history file")
        try:
            resolved = app.sandbox.resolve_read(history_path)
        except Exception as exc:
            return tool_error(f"Invalid history_path: {exc}")
        if not resolved.real.exists() or not resolved.real.is_file():
            return tool_error(f"history_path not found: {history_path}")
        resolved_history_path = str(resolved.real)

    try:
        orch = app.subagent_orchestrator
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
    name="RunSubAgent",
    toolset="multiagent",
    schema={
        # 从动态发现的角色档案启动一个子Agent会话。
        #
        # ## 前置条件
        # name 对应的角色目录必须同时包含 profile.md 和 profile.md.meta；
        # profile.md.meta 必须包含引用现有 LLM Profile 的 [llm_profile] 字段；可选的 [profile] 字段按行声明附加系统提示词路径。
        # 角色名称跨 roleplay/task 全局唯一；无效或重名角色会拒绝启动。
        #
        # ## 调用效果
        # 每次启动都会重新读取角色档案和当前引用的 LLM Profile，不需要显式注册。
        # initial_prompt 是发送给子Agent的第一条消息。
        # 不传 history_path 时不继承历史；传入时必须是 .es easysave 历史逻辑路径。
        # 活跃数量达到上限时进入 FIFO 等待队列，同一主会话下同一角色不能重复运行。
        #
        # ## 返回
        # {"success": true, "session_id": "...", "waiting": false}
        #
        # ## 何时使用
        # - 启动 roleplay 或 task 角色执行任务。
        # - 显式传入 history_path 恢复已保存的 .es 历史。
        #
        # ## 副作用/注意
        # - 角色档案缺失、元数据错误、Profile 不存在或名称冲突时不创建会话。
        # - 省略 history_path 始终从空历史开始。
        # - StopSubAgent 默认将历史保存到 ws:tmp/<session_id>.es。
        "description": """Start a sub-agent from a dynamically discovered character profile.

## Prerequisites
The character directory must contain `profile.md` and `profile.md.meta`. The metadata must contain a valid `[llm_profile]` reference to an existing LLM Profile. An optional `[profile]` section can list additional sandbox namespace paths, one per line; each file is loaded as a separate system prompt after `profile.md`. Use `ListSubAgents` to inspect available characters and errors.

## Effect
Each call creates a new sub-agent session from the current character files and current referenced LLM Profile. Character files and LLM configuration are read dynamically; no explicit registration step exists.

`initial_prompt` is the first message sent to the sub-agent. `history_path` is optional. If omitted, no history is inherited. If provided, it must be a sandbox logical path to an easysave `.es` history file, such as `ws:tmp/<session_id>.es`.

The sub-agent can use the tools available to the SUBAGENT scope. If the active sub-agent limit is reached, the session enters the FIFO waiting queue. The same character cannot have two active or queued sessions under one parent session.

## Returns
```json
{"success": true, "session_id": "...", "waiting": false}
```

## When to Use
- Run a task or role from `ws:characters/roleplay/` or `ws:characters/task/`.
- Explicitly resume a saved `.es` history by passing `history_path`.

## Side Effects / Notes
- Invalid, missing, or duplicate character profiles are rejected and do not create a session.
- Omitting `history_path` always starts with an empty sub-agent history.
- The default history saved by `StopSubAgent` is temporary and returned as `ws:tmp/<session_id>.es`.""",
        "parameters": {
            "type": "object",
            "properties": {
                # 角色目录名，必须全局唯一。
                "name": {
                    "type": "string",
                    "description": "Unique character directory name under ws:characters/.",
                },
                # 采样温度，默认 1.0，取值范围 0.0–1.3。
                "temperature": {
                    "type": "number",
                    "description": "Sampling temperature. Default 1.0, clamped to 0.0–1.3.",
                    "default": 1.0,
                },
                # 发送给子Agent的首条任务消息。
                "initial_prompt": {
                    "type": "string",
                    "description": "The first task message sent to the sub-agent.",
                },
                # 本轮消息发送者名称。
                "user_name": {
                    "type": "string",
                    "description": "The sender identity for this message.",
                },
                # 消息类型：direct 表示直接要求子Agent响应，overheard 表示旁听。
                "message_type": {
                    "type": "string",
                    "description": "Message type: direct or overheard.",
                },
                # 可选的 .es 历史逻辑路径；只有显式传入时才恢复历史。
                "history_path": {
                    "type": "string",
                    "description": "Optional logical path to an easysave .es history file. History is loaded only when this is explicitly provided.",
                },
            },
            "required": ["name", "initial_prompt", "user_name", "message_type"],
        },
    },
    handler=_handle_run_subagent,
    is_async=True,
    danger_level=ToolDangerLevel.safe,
    availability=ToolAvailability.MAIN,
)
