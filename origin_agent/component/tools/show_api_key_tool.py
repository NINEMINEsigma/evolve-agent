"""LLM API Key 展示工具 — 在前端显示可一键复制的浮动横幅（自动消失）。

模块导入时通过 ``registry.register()`` 注册 1 个工具：
  - ``show_llm_api_key`` — 读取当前 LLM API key 并推送到前端横幅

安全设计：
- 明文 key 只经 ``emit_clipboard_display`` 通过 WebSocket 直达前端（用户复制）；
- 返回给 agent 的 tool_result 仅含脱敏摘要（``sk-***wxyz``），不落会话历史 / 磁盘；
- 不注册 ui_event_router（避免明文经 result 二次进入 emit 通道）。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from abstract.tools.registry import registry, tool_result
from entity.puretype import ShowApiKeyResult, ToolAvailability, ToolDangerLevel

if TYPE_CHECKING:
    from entry.base_agent_loop import ToolContext

logger = logging.getLogger(__name__)

# 前端横幅自动消失时长（秒）
_BANNER_TTL_SECONDS = 60


def _mask_key(key: str) -> str:
    """脱敏：sk-abc...wxyz → sk-***wxyz；长度≤8 时全遮。"""
    if len(key) <= 8:
        return "***"
    return f"{key[:3]}***{key[-4:]}"


# ── handler ─────────────────────────────────────────────────────────


async def _handle_show_llm_api_key(args: dict[str, Any], context: ToolContext | None = None) -> dict:
    """读取当前 LLM API key 并推送到前端横幅，返回脱敏摘要。

    参数：无。
    调用效果：前端顶部出现可一键复制的密钥横幅，60 秒后自动消失，
    用户点击复制后立即消失。
    返回：{ configured, masked, message } —— 不含明文 key。
    """
    session_id: str = str(args.get("_session_id", ""))
    key: str = context.runtime_context.llm_api_key if context else ""

    if not key:
        return tool_result(**ShowApiKeyResult(
            configured=False,
            message="LLM API key 未配置",
        ).model_dump())

    # 直推前端：明文只走 WS 事件，不进 tool_result / 会话历史 / 磁盘
    if context is not None:
        payload = json.dumps({
            "display_id": "llm_api_key",
            "label": "LLM API Key",
            "content": key,
        }, ensure_ascii=False)
        await context.sink.emit_clipboard_display(session_id, "show_llm_api_key", payload)

    logger.info("LLM API key displayed | session=%s masked=%s", session_id, _mask_key(key))

    return tool_result(**ShowApiKeyResult(
        configured=True,
        masked=_mask_key(key),
        message=f"已在前端展示 LLM API Key（{_BANNER_TTL_SECONDS} 秒后自动消失）",
    ).model_dump())


# ── 注册 ────────────────────────────────────────────────────────────

registry.register(
    name="show_llm_api_key",
    toolset="core",
    schema={
        # 在前端顶部显示可一键复制的 LLM API Key 浮动横幅，60 秒后自动消失。
        # 前置条件：前端在线；当前 LLM 已配置 api_key。
        # 调用效果：前端出现含完整 key 的横幅，用户点击复制后立即消失。
        # 返回：{ configured, masked, message } —— 仅脱敏摘要，明文不进入会话历史。
        # 使用限制：仅展示主 LLM 的 api_key；未配置时返回 configured=False 不推送。
        # 典型场景：用户需要复制自己的 API key（换机器、配其他服务等）。
        # 副作用：仅影响前端 UI，不写入剪贴板，不落盘。
        "description": """Display the current LLM API key in a floating frontend banner (auto-dismiss, one-click copy).

## Prerequisites
Frontend must be online. The LLM api_key must be configured.

## Effect
A floating banner containing the full API key appears at the top of the frontend. It auto-dismisses after 60 seconds, or immediately when the user clicks copy.

## Returns
```json
{ "configured": true, "masked": "sk-***wxyz", "message": "..." }
```
The masked summary only — the plaintext key is pushed directly to the frontend and never enters the conversation history or disk.

## Usage Rules
- Display the main LLM api_key only.
- If not configured, returns `configured: false` and pushes nothing.

## When to Use
- The user needs to copy their API key (e.g. for another machine or service).

## Side Effects
Frontend UI only. Does not write to the system clipboard and does not persist anything.""",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    handler=_handle_show_llm_api_key,
    is_async=True,
    emoji="🔑",
    danger_level=ToolDangerLevel.readonly,
    availability=ToolAvailability.MAIN,
)