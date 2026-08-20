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

import logging
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result
from entity.puretype import ToolAvailability, ToolDangerLevel

logger = logging.getLogger(__name__)


# ── 工具 handler ─────────────────────────────────────────────

async def _handle_ask_question(args: dict[str, Any]) -> dict:
    """向用户提问，等待回答后返回结果。

    预期参数：
        question:   str       — 要问的问题（简短标题，不用 markdown）
        detail:     str       — 问题的详细说明（可选，支持 markdown）
        options:    list[dict] — 预设选项列表，每项 {label, value}（可选）
    """
    from system.application import Application

    question: str = str(args.get("question", "")).strip()
    detail: str = str(args.get("detail", "")).strip()
    raw_options: Any = args.get("options")
    session_id: str = str(args.get("_session_id", ""))

    if not question:
        return tool_error("'question' is required")

    # 标准化 options
    options: list[dict[str, str]] = []
    if raw_options and isinstance(raw_options, list):
        for item in raw_options:
            if isinstance(item, dict):
                label = str(item.get("label", item.get("value", "")))
                value = str(item.get("value", item.get("label", "")))
                if label and value:
                    options.append({"label": label, "value": value})
            elif isinstance(item, str):
                options.append({"label": item, "value": item})

    if not session_id:
        return tool_error("Missing session_id, cannot send question")

    sink = Application.current().frontend_sink
    if sink is None:
        return tool_error("FrontendSink not available")

    result = await sink.ask_question(
        question=question,
        detail=detail,
        options=options,
        session_id=session_id,
    )

    if "error" in result:
        return tool_error(result["error"])

    return tool_result(
        question=result.get("question"),
        option=result.get("option"),
        custom_text=result.get("custom_text"),
        answered=result.get("answered", False),
    )


# ── 注册 ─────────────────────────────────────────────────────

registry.register(
    name="Ask",
    toolset="core",
    schema={
        # 向当前用户提问，支持预设选项和自定义输入。
        # 前置条件：必须有活跃的 WebSocket 连接（前端在线）。无连接时调用会失败。
        # 调用效果：agent 阻塞等待用户回答（永不超时）。阻塞期间 agent 不处理其他任务。
        # 字段指南：question 为简短纯文本标题（不用 markdown），detail 为可选的 markdown 详细说明。
        # 返回格式：{ question, option: 选中项的 value, custom_text: 自由文本, answered: bool }
        # 未选择也未输入时 answered=false。
        # 典型场景：需要用户决策（文件处理方式、多选一）、收集偏好、确认操作。
        # 副作用：agent 线程阻塞直到用户响应，不应在后台任务中调用。
        # 备注：用户始终可以自定义输入回答，不受 options 限制。
        "description": """Ask the current user a question with preset options to choose from. The user can always type a custom answer regardless of the preset options.

## Prerequisites
An active WebSocket connection is required (the frontend must be online). Calling without one will fail.

## Field Guidelines
- `question`: A short, plain-text title shown in the dialog header. Do NOT use markdown formatting (no `**bold**`, no code blocks, no tables). Keep it concise — ideally one sentence.
- `detail`: Optional. A markdown-rendered explanation shown in the dialog body. Use this for complex context, code examples, tables, or multi-paragraph descriptions. If the question is simple enough to fit in one line, omit `detail`.

## Effect
The agent blocks and waits for the user's response indefinitely (no timeout). The agent cannot process other tasks while waiting.

## Returns
```json
{ "question": "<asked>", "option": "<selected value>", "custom_text": "<free text>", "answered": true|false }
```
`answered` is `false` when the user neither selects an option nor enters custom text.

## When to Use
- Asking the user how to handle a file.
- Letting the user choose from multiple options.
- Collecting user preferences or confirmation.

## Side Effects
The agent thread blocks until the user responds. Do not call this inside background tasks.""",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    # 显示给用户的问题标题。简短纯文本，不应使用 markdown 格式。必需。
                    "description": """The question text to display to the user. Required.""",
                },
                "detail": {
                    "type": "string",
                    # 问题的详细说明，支持 markdown 格式渲染。可选。
                    # 当问题需要复杂描述（多段文本、代码块、表格、列表等）时使用。
                    "description": """Optional detailed explanation of the question, rendered as markdown. Use this for complex context, code blocks, tables, or multi-paragraph descriptions. Keep `question` short and plain.""",
                },
                "options": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string", "description": """Display text for the option."""},
                            "value": {"type": "string", "description": """Value of the option."""},
                        },
                        "required": ["label", "value"],
                    },
                    # 预设选项列表。每项包含 label（显示文本）和 value（返回值）。
                    # 用户始终可以自定义输入回答，与预设选项并存。
                    "description": """List of preset options, each with a `label` (display text) and `value` (returned value). The user can always type a custom answer regardless.""",
                },
            },
            "required": ["question"],
        },
    },
    handler=_handle_ask_question,
    is_async=True,
    emoji="❓",
    danger_level=ToolDangerLevel.safe,
    no_timeout=True,
    availability=ToolAvailability.MAIN | ToolAvailability.MULTI_AGENT,
    resets_turn_counter=True,
)