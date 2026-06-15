"""剪贴板展示工具 — 在前端顶部显示可一键复制的文本区域。

模块导入时通过 ``registry.register()`` 注册 2 个工具：
  - ``set_clipboard_display``  — 创建或更新可复制展示区域
  - ``clear_clipboard_display`` — 清除展示区域

由 ``AgentLoop._execute_tool`` 检测后通过 ``clipboard_display`` 事件推送到前端。
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from abstract.tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)


# ── 内部状态：session_id → {display_id → display_info} ─────────────────

_display_registry: dict[str, dict[str, dict[str, Any]]] = {}


# ── handler ─────────────────────────────────────────────────────────


async def _handle_set_clipboard_display(args: dict[str, Any]) -> dict:
    """创建或更新前端可复制展示区域。

    参数：
        display_id: 展示区域唯一标识（同一 display_id 会覆盖更新）
        label:      展示区域标题/描述
        content:    要展示的文本内容，点击即可复制
    """
    display_id: str = str(args.get("display_id", "")).strip()
    label: str = str(args.get("label", "")).strip()
    content: str = str(args.get("content", ""))
    session_id: str = str(args.get("_session_id", ""))

    if not display_id:
        return tool_error("'display_id' is required")

    info: dict[str, Any] = {
        "display_id": display_id,
        "label": label or display_id,
        "content": content,
    }

    if session_id:
        _display_registry.setdefault(session_id, {})[display_id] = info

    logger.info("Clipboard display updated | session=%s display=%s", session_id, display_id)

    return tool_result(**info)


async def _handle_clear_clipboard_display(args: dict[str, Any]) -> dict:
    """清除前端指定展示区域。

    参数：
        display_id: 要清除的展示区域标识。不提供则清除该会话所有展示区域。
    """
    display_id: str = str(args.get("display_id", "")).strip()
    session_id: str = str(args.get("_session_id", ""))

    cleared: list[str] = []
    if session_id and session_id in _display_registry:
        if display_id:
            if display_id in _display_registry[session_id]:
                del _display_registry[session_id][display_id]
                cleared.append(display_id)
        else:
            cleared = list(_display_registry[session_id].keys())
            _display_registry[session_id].clear()

    logger.info("Clipboard display cleared | session=%s displays=%s", session_id, cleared)

    return tool_result(
        success=True,
        cleared=cleared,
        message=f"Cleared clipboard display: {', '.join(cleared) if cleared else 'none'}"
    )


# ── 注册 ────────────────────────────────────────────────────────────

registry.register(
    name="set_clipboard_display",
    toolset="clipboard",
    schema={
        "description": (
            "**ALWAYS use this tool immediately** when the user asks to copy something, or when you generate any long text "
            "(tags, prompts, keywords, code snippets, configuration, comma-separated lists, etc.) that the user is likely to copy.\n"
            "Do NOT paste the text into the chat message and ask the user to manually select/copy it. "
            "Instead, call this tool so the user can copy with a single click from the top panel.\n\n"
            "Common triggers:\n"
            "- User says '让我复制' / 'copy this' / '给我复制' / '复制出来'\n"
            "- You produce a long list of tags, prompts, or keywords\n"
            "- You generate code, config, or any text the user will reuse\n\n"
            "The same display_id will overwrite the existing display area.\n"
            "Returns the current display metadata."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "display_id": {
                    "type": "string",
                    "description": "Unique identifier for this display area. Reusing the same ID updates it.",
                },
                "label": {
                    "type": "string",
                    "description": "Human-readable title/description of the content.",
                },
                "content": {
                    "type": "string",
                    "description": "The text content to display and copy.",
                },
            },
            "required": ["display_id", "label", "content"],
        },
    },
    handler=_handle_set_clipboard_display,
    is_async=True,
    emoji="📋",
    danger_level="readonly",
)

registry.register(
    name="clear_clipboard_display",
    toolset="clipboard",
    schema={
        # 从前端移除指定可复制展示区域。
        # 省略 display_id 时清除当前会话的所有展示区域。
        "description": (
            "Remove a copy-to-clipboard display area from the frontend.\n"
            "If display_id is omitted, all display areas for the current session are cleared.\n\n"
            "Returns the list of cleared display IDs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "display_id": {
                    "type": "string",
                    "description": "display_id of the area to clear. Omit to clear all.",
                },
            },
            "required": [],
        },
    },
    handler=_handle_clear_clipboard_display,
    is_async=True,
    emoji="🧹",
    danger_level="readonly",
)