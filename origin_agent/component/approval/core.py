"""审批流程核心入口 — 统一审批入口和 Agent 主模型提问回调。

对外暴露：
- request_user_confirm: 统一的审批入口，自动分流脱手模式与正常模式
- ask_agent_reason: 脱手模式专用，向 Agent 主模型提问获取上下文
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, Optional, TYPE_CHECKING

from entity.puretype import ApprovalResult, Role
from entity.messages import BaseMessage

if TYPE_CHECKING:
    from abstract.llm.client import BaseLLMClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 统一审批入口
# ---------------------------------------------------------------------------

async def request_user_confirm(
    session_id: str,
    tool_name: str,
    args: dict,
    reason: str,
    content: str,
    ask_agent_callback: Optional[Callable[[str], Awaitable[str]]] = None,
    extra_context: str | None = None,
) -> ApprovalResult:
    """统一审批入口。

    参数：
        session_id: WebSocket session ID
        tool_name:  工具名（如 "run_command"、"install_package"）
        args:       工具调用参数字典
        reason:     agent 给出的执行原因
        content:    展示给审批者的描述文本
        ask_agent_callback: 可选 — 脱手模式专用。当审批模型不确定时，
                            通过此回调向 Agent 主模型提问，获取更多上下文。
        extra_context: 可选 — custom_hooks 等额外上下文，供审批模型参考。

    返回 ApprovalResult(action, deny_reason)。
    """
    from component.approval.handsfree import _handsfree_confirm, is_handsfree_mode

    # 脱手模式：LLM 自动审批（不占用工具调用超时时间）
    if is_handsfree_mode(session_id):
        result = await _handsfree_confirm(
            tool_name, args, reason, content,
            ask_agent_callback=ask_agent_callback,
            extra_context=extra_context,
        )
        if result is not None:
            return result
        # approver 不可用 → 回退到人工审批

    # 正常模式：通过 FrontendSink 请求审批
    from system.application import Application
    return await Application.current().frontend_sink.request_approval(
        tool_name=tool_name,
        args=args,
        reason=reason,
        content=content,
        session_id=session_id,
    )


# ---------------------------------------------------------------------------
# 脱手模式辅助 — 向 Agent 主模型提问以获取审批上下文
# ---------------------------------------------------------------------------

async def ask_agent_reason(
    llm: BaseLLMClient,
    tool_name: str,
    tool_args: dict,
    question: str,
    extra_context: str | None = None,
) -> str:
    """将审批模型的问题转发给 Agent 主模型，获取操作意图解释。

    当脱手模式的 LLM 不确定时，通过此函数向主模型提问，
    主模型的回答会追加到提示词中供审批模型重新评估。

    参数：
        llm:       Agent 主模型 BaseLLMClient 实例
        tool_name: 被审批的工具名
        tool_args: 工具参数字典
        question:  审批模型提出的问题
        extra_context: 可选 — custom_hooks 等额外上下文

    返回：
        主模型的回答文本
    """
    from system.templates import read_template

    ask_prompt = (
        read_template("approval/ask_agent_prompt.md")
        .replace("{{tool_name}}", tool_name)
        .replace("{{question}}", question)
        .replace("{{tool_args_json}}", json.dumps(tool_args, ensure_ascii=False, indent=2))
    )
    if extra_context:
        ask_prompt += "\n\n" + read_template("approval/ask_agent_extra_context.txt").replace("{{extra_context}}", extra_context)
    try:
        resp = await llm.chat(
            [BaseMessage(role=Role.USER, content=ask_prompt)],
            tools=[],
        )
        return resp.content or "(Agent did not provide an explanation)"
    except Exception as exc:
        logger.exception("Failed to ask agent for clarification: %s", exc)
        return f"(Failed to get agent explanation: {exc})"