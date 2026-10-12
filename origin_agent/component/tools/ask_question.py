"""提问工具 — agent 向用户提问，提供预设选项和/或自定义输入。

显式注册协议：模块导出 ``register_tools(registry, ui_events)`` 函数。
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

from abstract.tools.registry import ToolRegistry, tool_error, tool_result
from abstract.tools.ui_event_router import UIEventRouter
from entity.puretype import ToolAvailability, ToolDangerLevel

logger = logging.getLogger(__name__)


# ── 工具 handler ─────────────────────────────────────────────

async def _handle_ask_question(args: dict[str, Any]) -> dict:
    """向用户提问（多问题表单），等待回答后返回结果。

    预期参数：
        questions:  list[dict] — 问题列表，每项 {question, detail?, options?, multi_select?}
    """
    from system.application import Application

    raw_questions: Any = args.get("questions")
    session_id: str = str(args.get("_session_id", ""))

    if not isinstance(raw_questions, list) or not raw_questions:
        return tool_error("'questions' must be a non-empty list of question objects")

    # 标准化 questions：每项 question 必填非空；options 支持 dict/str 双形态；multi_select 默认 False
    questions: list[dict[str, Any]] = []
    for item in raw_questions:
        if not isinstance(item, dict):
            return tool_error("each question must be an object with a 'question' field")
        question: str = str(item.get("question", "")).strip()
        if not question:
            return tool_error("'question' is required for every question")
        detail: str = str(item.get("detail", "") or "").strip()
        multi_select: bool = bool(item.get("multi_select", False))
        raw_options: Any = item.get("options")
        options: list[dict[str, str]] = []
        if raw_options and isinstance(raw_options, list):
            for opt in raw_options:
                if isinstance(opt, dict):
                    label = str(opt.get("label", opt.get("value", "")))
                    value = str(opt.get("value", opt.get("label", "")))
                    if label and value:
                        options.append({"label": label, "value": value})
                elif isinstance(opt, str):
                    options.append({"label": opt, "value": opt})
        questions.append({
            "question": question,
            "detail": detail,
            "options": options,
            "multi_select": multi_select,
        })

    if not session_id:
        return tool_error("Missing session_id, cannot send question")

    # QUESTION: 按时序必须是注册完成的
    from entry.agent_sink import FrontendSink
    try:
        sink = Application.current().get_system(FrontendSink)
    except RuntimeError:
        return tool_error("FrontendSink not available")

    result = await sink.ask_question(
        questions=questions,
        session_id=session_id,
    )

    if "error" in result:
        return tool_error(result["error"])

    answers_raw: list[dict] | None = result.get("answers")
    answers: list[dict[str, Any]] = []
    if answers_raw:
        for index, question_item in enumerate(questions):
            answer = answers_raw[index] if index < len(answers_raw) else {}
            selected: list[str] = [str(v) for v in (answer.get("selected") or [])]
            custom_text = answer.get("custom_text")
            custom_text = str(custom_text) if custom_text else None
            answers.append({
                "question": question_item["question"],
                "selected": selected,
                "custom_text": custom_text,
                "answered": bool(selected) or custom_text is not None,
            })

    return tool_result(
        questions=questions,
        answers=answers,
        answered=result.get("answered", False),
    )


# ── schema 常量 ─────────────────────────────────────────────

_ASK_SCHEMA = {
    # 向当前用户提问（多问题表单），每题支持预设选项（单选/多选）与自定义文本输入。
    # 前置条件：必须有活跃的 WebSocket 连接（前端在线）。无连接时调用会失败。
    # 调用效果：agent 阻塞等待用户提交整张表单（永不超时）。阻塞期间 agent 不处理其他任务。
    # 返回格式：{ questions, answers: [{question, selected, custom_text, answered}], answered }
    # 典型场景：需要用户决策（文件处理方式、多项配置选择）、收集偏好、确认操作。
    # 副作用：agent 线程阻塞直到用户响应，不应在后台任务中调用。
    "description": """Ask the user a multi-question form: pass 1 to N related questions in ONE call and the user answers them together (paged wizard in the UI, submitted at the final question). Each question independently supports preset options (single-select or multi-select) and free-text input; the two may coexist.

## Prerequisites
An active WebSocket connection is required (the frontend must be online). Calling without one will fail.

## Field Guidelines
- `questions`: Required, non-empty array. Each item is one question:
  - `question` (required): Short plain-text title. Do NOT use markdown. Keep it to one sentence.
  - `detail` (optional): Markdown-rendered explanation of this question. Use for complex context, code examples, tables, or multi-paragraph descriptions.
  - `options` (optional): Array of `{label, value}` preset choices for this question.
  - `multi_select` (optional, default false): true lets the user pick MULTIPLE options of this question; false = single-select (at most one option). No upper limit when multi-select.
- Batch related decisions into one call instead of asking one question at a time — the user fills the whole form and submits once. Unrelated topics may be split across calls.

## Effect
The agent blocks and waits for the user's response indefinitely (no timeout). The agent cannot process other tasks while waiting.

## Returns
```json
{
  "questions": [ ... the normalized questions you asked ... ],
  "answers": [
    { "question": "<asked>", "selected": ["<value>"], "custom_text": "<free text or null>", "answered": true }
  ],
  "answered": true
}
```
`answers` order matches `questions` order. Per question: `selected` is the array of chosen option values (empty if none), `custom_text` is free text (null if none) — both may be present simultaneously; `answered` is false when the user neither selected nor typed. Top-level `answered` is false only when the user skipped the whole form. Unanswered questions return empty `selected` and null `custom_text` — if you need all answers, re-ask.

## When to Use
- Letting the user choose one or more items (single-select or multi-select per question).
- Collecting several preferences or confirmations in one interaction.
- Asking the user how to handle a file or task.

## Side Effects
The agent thread blocks until the user responds. Do not call this inside background tasks.""",
    "parameters": {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                # 问题列表。每项包含 question（必需）、detail、options、multi_select。
                # 相关决策应合并进一次调用，用户填写整张表单后一次性提交。
                "description": """Array of 1 to N questions, answered together in one form. Each item: `question` (required, short plain-text title), `detail` (optional markdown explanation), `options` (optional array of {label, value}), `multi_select` (optional, default false — true allows selecting multiple options for this question).""",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            # 显示给用户的问题标题。简短纯文本，不应使用 markdown 格式。必需。
                            "description": """The question text to display to the user. Required.""",
                        },
                        "detail": {
                            "type": "string",
                            # 该题的详细说明，支持 markdown 格式渲染。可选。
                            "description": """Optional detailed explanation of this question, rendered as markdown.""",
                        },
                        "options": {
                            "type": "array",
                            # 该题的预设选项列表。每项包含 label（显示文本）和 value（返回值）。
                            "description": """Optional preset options for this question, each with a `label` and `value`.""",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "label": {"type": "string", "description": """Display text for the option."""},
                                    "value": {"type": "string", "description": """Value of the option."""},
                                },
                                "required": ["label", "value"],
                            },
                        },
                        "multi_select": {
                            "type": "boolean",
                            # 是否允许多选。默认 false（单选，最多选 1 项）。true 时无选择上限。
                            "description": """Allow selecting multiple options for this question. Default false (single-select, at most one option).""",
                        },
                    },
                    "required": ["question"],
                },
            },
        },
        "required": ["questions"],
    },
}


# ── 注册 ─────────────────────────────────────────────────────

def register_tools(registry: ToolRegistry, ui_events: UIEventRouter) -> None:
    """Register the Ask tool into the explicit runtime registry."""
    del ui_events  # Ask has no UI event handler
    registry.register(
        name="Ask",
        toolset="core",
        schema=_ASK_SCHEMA,
        handler=_handle_ask_question,
        is_async=True,
        danger_level=ToolDangerLevel.safe,
        no_timeout=True,
        availability=ToolAvailability.MAIN | ToolAvailability.MULTI_AGENT,
        resets_turn_counter=True,
    )
