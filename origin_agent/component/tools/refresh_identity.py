"""主Agent身份刷新工具。

显式注册协议：模块导出 ``register_tools(registry, ui_events)`` 注册工具。
``RefreshIdentity`` 重新读取 ``ws:SOUL.md.meta`` 的 ``[character_name]`` 字段，
刷新运行时主Agent角色名。普通模式与随意聊聊会话的主Agent可用；仅供安全操作，
不涉及文件系统写权限。
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from abstract.tools.registry import ToolRegistry, tool_result
from abstract.tools.ui_event_router import UIEventRouter
from entity.puretype import ToolAvailability, ToolDangerLevel
from entity.constant import SOUL_META_CHARACTER_NAME_KEY
from system.application import Application
from system.runtime import RuntimeSystem

if TYPE_CHECKING:
    from entry.base_agent_loop import ToolContext

# SOUL.md.meta 解析后的取值说明（用于工具返回与提示词对齐）。
_DEFAULT_SOUL_FILE: str = "SOUL.md"


def _handle_refresh_identity(
    args: dict[str, Any],
    context: ToolContext | None = None,
) -> dict:
    """重新读取 SOUL.md.meta 并刷新主Agent角色名。"""
    del args, context
    runtime = Application.current().get_system(RuntimeSystem)
    soul_file_name = _DEFAULT_SOUL_FILE
    new_name = runtime.refresh_main_agent_character_name(soul_file_name)
    return tool_result(
        success=True,
        main_agent_character_name=new_name,
        soul_meta_file=f"ws:{soul_file_name}.meta",
        meta_key=SOUL_META_CHARACTER_NAME_KEY,
    )


_REFRESH_IDENTITY_SCHEMA = {
    "description": """Refresh the running main Agent's character name from its SOUL metadata file.

## Effect
- Reads ``ws:SOUL.md.meta`` and applies the ``[character_name]`` value as the main Agent's character name.
- If the file or the key is absent, or the file is malformed, the name falls back to the default ``main-agent``.
- The refreshed name is process-wide: it governs how the main Agent is addressed in History, the frontend, and multi-Agent routing.

## When to Use
- After you have edited ``[character_name]`` in ``ws:SOUL.md.meta`` and want the new name to take effect immediately.
- Changes apply only after this tool runs; editing the file alone does not reload the name.

## Returns
```json
{ "success": true, "main_agent_character_name": "<name>", "soul_meta_file": "ws:SOUL.md.meta", "meta_key": "character_name" }
```""",
    "parameters": {
        "type": "object",
        "properties": {},
    },
}


def register_tools(registry: ToolRegistry, ui_events: UIEventRouter) -> None:
    """Register the RefreshIdentity tool."""
    del ui_events  # RefreshIdentity has no UI event handler
    registry.register(
        name="RefreshIdentity",
        toolset="core",
        schema=_REFRESH_IDENTITY_SCHEMA,
        handler=_handle_refresh_identity,
        danger_level=ToolDangerLevel.safe,
        availability=ToolAvailability.MAIN,
    )
