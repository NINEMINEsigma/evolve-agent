"""提问工具 — agent 向用户提问，提供预设选项和/或自定义输入。

模块导入时通过 ``registry.register()`` 注册。
工作流程：
  1. agent 调用 ask_question，传入问题、选项列表和是否允许自定义输入
  2. 服务端通过 WebSocket 向前端推送 ask_request 消息
  3. 前端展示问题对话框，用户选择或输入后提交
  4. 结果通过 HTTP POST /api/ask/{request_id} 或 WebSocket ASK_RESPONSE 返回
  5. 工具返回用户的选择
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, List

from abstract.tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)


# ── 工具 handler ─────────────────────────────────────────────

async def _handle_ask_question(args: Dict[str, Any]) -> str:
    """向用户提问，等待回答后返回结果。

    预期参数：
        question:   str       — 要问的问题
        options:    list[dict] — 预设选项列表，每项 {label, value}（可选）
        allow_custom: bool    — 是否允许用户自定义输入（默认 true）
    """
    # 延迟导入以避免与 gateway.server 的循环依赖
    from gateway.server import _tool_ws_sinks, _pending_asks, _register_ask_session
    question: str = str(args.get("question", "")).strip()
    raw_options: Any = args.get("options")
    allow_custom: bool = bool(args.get("allow_custom", True))
    session_id: str = str(args.get("_session_id", ""))

    if not question:
        return tool_error("'question' is required")

    # 标准化 options
    options: List[Dict[str, str]] = []
    if raw_options and isinstance(raw_options, list):
        for item in raw_options:
            if isinstance(item, dict):
                label = str(item.get("label", item.get("value", "")))
                value = str(item.get("value", item.get("label", "")))
                if label and value:
                    options.append({"label": label, "value": value})
            elif isinstance(item, str):
                options.append({"label": item, "value": item})

    if not options:
        # 无预设选项时默认允许自定义输入
        allow_custom = True

    if not session_id:
        return tool_error("缺少 session_id，无法发送提问")

    # ── 注册异步等待 ──
    request_id: str = uuid.uuid4().hex[:8]
    loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
    fut: asyncio.Future[str] = loop.create_future()
    _pending_asks[request_id] = fut
    _register_ask_session(request_id, session_id)

    # ── 通过 WebSocket 推送提问消息到前端 ──
    ws = _tool_ws_sinks.get(session_id)
    if ws:
        try:
            await ws.send_text(json.dumps({
                "type": "ask_request",
                "session_id": session_id,
                "request_id": request_id,
                "question": question,
                "options": options,
                "allow_custom": allow_custom,
            }, ensure_ascii=False))
        except Exception as exc:
            _pending_asks.pop(request_id, None)
            return tool_error(f"WebSocket 推送提问消息失败: {exc}")
    else:
        _pending_asks.pop(request_id, None)
        return tool_error("WebSocket 连接不可用，无法发送提问")

    # ── 等待用户回答（最多 600 秒）──
    try:
        result_str: str = await asyncio.wait_for(fut, timeout=600.0)
        result: dict = json.loads(result_str)
        return tool_result(
            question=question,
            option=result.get("option"),
            custom_text=result.get("custom_text"),
            answered=result.get("option") is not None or result.get("custom_text") is not None,
        )
    except asyncio.CancelledError:
        _pending_asks.pop(request_id, None)
        return tool_error("提问请求被取消")
    except asyncio.TimeoutError:
        _pending_asks.pop(request_id, None)
        return tool_error("用户回答超时（600s）")
    except Exception as exc:
        _pending_asks.pop(request_id, None)
        return tool_error(f"提问处理异常: {exc}")


# ── 注册 ─────────────────────────────────────────────────────

registry.register(
    name="ask_question",
    toolset="core",
    schema={
        "description": (
            "向当前用户提问，提供预设选项供选择，并可选择允许用户自定义输入。\n\n"
            "适用于需要用户决策的场景，如：\n"
            "  - 询问用户想要怎么处理某个文件\n"
            "  - 让用户从多个方案中选择一个\n"
            "  - 收集用户的偏好或确认信息\n\n"
            "返回用户选择的 option（选项的 value）和/或 custom_text（自定义输入）。\n"
            "如果用户未选择任何选项也未输入自定义文本，answered 字段为 false。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "要向用户提出的问题。",
                },
                "options": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string", "description": "显示的选项文本"},
                            "value": {"type": "string", "description": "选项的值"},
                        },
                        "required": ["label", "value"],
                    },
                    "description": "预设选项列表，每项包含 label（显示文本）和 value（返回值）。留空或 null 时仅允许自定义输入。",
                },
                "allow_custom": {
                    "type": "boolean",
                    "description": "是否允许用户输入自定义文本（默认 true）。设为 false 时用户必须在预设选项中做出选择。",
                    "default": True,
                },
            },
            "required": ["question"],
        },
    },
    handler=_handle_ask_question,
    is_async=True,
    emoji="❓",
    danger_level="readonly",
)