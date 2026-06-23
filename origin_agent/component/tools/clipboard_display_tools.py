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
        # 在前端顶部创建或更新可一键复制的展示区域。
        # 前置条件：无（前端在线即可）。display_id 重复使用会覆盖更新而非追加。
        # 调用效果：前端顶部出现可复制文本卡片，用户点击即可复制。
        # 返回：{ display_id, label, content }
        # 使用限制：最多同时保留 2 个展示区域，除非用户明确要求更多。
        #   内容发生变化时应主动调用本工具更新对应 display_id 的卡片。
        #   感觉用户已不再需要某卡片时应主动调用 clear_clipboard_display 关闭。
        # 典型场景：用户要求复制内容、生成长文本（代码、配置、标签列表）时。
        # 副作用：仅影响前端 UI，不涉及文件系统。不会将内容写入剪贴板。
        "description": """Create or update a one-click copy area in the frontend top panel.

## Prerequisites
None (frontend must be online).

## Effect
A copyable text card appears at the top of the frontend. The user can copy with a single click.

## Returns
```json
{ "display_id": "<id>", "label": "<title>", "content": "<text>" }
```

## Usage Rules
- **Limit**: keep at most 2 display areas simultaneously, unless the user explicitly requests more.
- **Update**: when content changes, proactively call this tool with the same `display_id` to update the card.
- **Cleanup**: when you sense the user no longer needs a card, proactively call `clear_clipboard_display` to remove it.

## When to Use
- The user asks to copy something (e.g. "copy this", "给我复制").
- You generate long text the user is likely to copy: code snippets, configs, keyword lists, comma-separated values, etc.
- Do NOT paste the text into the chat and ask the user to manually select/copy it. Use this tool instead.

## Side Effects
Frontend UI only. Does not write to the system clipboard. Reusing the same `display_id` overwrites the previous card.""",
        "parameters": {
            "type": "object",
            "properties": {
                "display_id": {
                    "type": "string",
                    # 展示区域唯一标识。重复使用同一 id 会覆盖更新。
                    "description": """Unique identifier for this display area. Reusing the same ID overwrites the existing card instead of creating a new one.""",
                },
                "label": {
                    "type": "string",
                    # 展示区域标题/描述。
                    "description": """Human-readable title shown above the content.""",
                },
                "content": {
                    "type": "string",
                    # 要展示的文本内容，用户点击即可复制。
                    "description": """The text content to display. The user can copy it with a single click.""",
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
        # 移除前端展示区域。
        # display_id: 要清除的展示区域 id。不传则清除当前会话全部展示区域。
        # 调用效果：前端对应卡片消失。
        # 返回：{ success, cleared: [...], message }
        # 使用规则：当感觉用户不再需要某卡片时，应主动调用本工具清理，保持面板整洁。
        "description": """Remove a clipboard display area from the frontend.

## Effect
The corresponding card disappears from the frontend top panel.

## Returns
```json
{ "success": true, "cleared": ["id1", ...], "message": "Cleared clipboard display: id1, ..." }
```

## Parameters
- `display_id`: ID of the area to clear. Omit to clear all areas for the current session.

## Usage Rule
Proactively call this tool when you sense the user no longer needs a card, to keep the panel clean.""",
        "parameters": {
            "type": "object",
            "properties": {
                "display_id": {
                    "type": "string",
                    # 要清除的展示区域 id。省略则清除当前会话全部。
                    "description": """ID of the display area to clear. Omit to clear all areas for the current session.""",
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