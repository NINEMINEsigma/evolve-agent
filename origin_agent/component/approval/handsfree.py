"""脱手模式审批 — 本地/远程 LLM 自动审批工具调用。

包含脱手模式 session 状态管理、审批 JSON Schema 定义和 _handsfree_confirm 核心流程。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Optional, cast

import dirtyjson

from entity.constant import LLM_RETRY_COUNT
from entity.puretype import ApprovalResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 脱手模式 session 注册表
# ---------------------------------------------------------------------------

_handsfree_sessions: dict[str, bool] = {}

def set_handsfree_mode(session_id: str, enabled: bool) -> None:
    """开启/关闭脱手模式。"""
    _handsfree_sessions[session_id] = enabled
    logger.info("Handsfree mode %s for session=%s", "enabled" if enabled else "disabled", session_id)


def is_handsfree_mode(session_id: str) -> bool:
    """返回该 session 是否处于脱手模式。"""
    return _handsfree_sessions.get(session_id, False)


# ---------------------------------------------------------------------------
# 审批输出 JSON Schema
# ---------------------------------------------------------------------------

APPROVAL_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "approved": {"type": "boolean"},
        "reason": {"type": "string"},
        "ask": {"type": "string"},
    },
    "required": ["approved"],
}


# ---------------------------------------------------------------------------
# 脱手模式：LLM 审批
# ---------------------------------------------------------------------------

async def _handsfree_confirm(
    tool_name: str, args: dict, reason: str, content: str,
    ask_agent_callback: Optional[Callable[[str], Awaitable[str]]] = None,
    max_dialog_turns: int = 2,
    extra_context: str | None = None,
) -> ApprovalResult:
    """脱手模式：将工具调用 JSON 发送给LLM 审批。

    支持 dialog 模式：当审批模型不确定时，可通过 ask_agent_callback
    向 Agent 主模型提问，获取更多上下文后重新评估。

    返回 ApprovalResult，deny 时携带 LLM 生成的拒绝原因。
    """
    backend = None
    try:
        from system.application import Application
        mgr = Application.current().approval_backend_manager
        if mgr is not None:
            backend = await mgr.get_backend()
    except Exception as exc:
        logger.warning("Failed to resolve approval backend: %s", exc, exc_info=True)
        backend = None
    if backend is None:
        logger.warning("Approver not available — handsfree mode deny")
        return ApprovalResult(action="deny", deny_reason="Approval backend unavailable, auto-denied", denied_by="system")

    from system.pathutils import find_repo_root, get_templates_dir

    system_prompt = (get_templates_dir() / "approval" / "system_prompt.md").read_text(encoding="utf-8")
    cwd = str(find_repo_root().resolve())

    user_prompt_data: dict[str, Any] = {
        "tool": tool_name,
        "args": args,
        "reason": reason,
        "cwd": cwd,
    }
    if extra_context:
        user_prompt_data["context"] = extra_context
    user_prompt = json.dumps(user_prompt_data, ensure_ascii=False)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    dialog_turn = 0
    last_error: str | None = None

    while dialog_turn <= max_dialog_turns:
        current_messages = list(messages)
        last_error = None
        resp_content: str | None = None

        for attempt in range(1, LLM_RETRY_COUNT + 1):
            try:
                resp_content = await backend.chat(current_messages, json_schema=APPROVAL_JSON_SCHEMA)
                result: dict = cast(dict, dirtyjson.loads(resp_content))

                # ---- 处理「ask」响应：审批模型不确定，向Agent提问 ----
                ask_question: str | None = result.get("ask")
                if ask_question and isinstance(ask_question, str) and ask_question.strip():
                    if ask_agent_callback is None or dialog_turn >= max_dialog_turns:
                        reason_text: str = cast(str, result.get("reason", ""))
                        logger.info(
                            "Handsfree ask but cannot continue | tool=%s question=%s",
                            tool_name, ask_question,
                        )
                        return ApprovalResult(
                            action="deny",
                            deny_reason=f"Approval model uncertain: {reason_text}" if reason_text else "Approval model needs more info but cannot continue dialog",
                            denied_by="model",
                        )

                    logger.info(
                        "Handsfree asking agent (turn %d/%d) | tool=%s question=%s",
                        dialog_turn + 1, max_dialog_turns, tool_name, ask_question,
                    )
                    agent_answer = await ask_agent_callback(ask_question)
                    logger.info(
                        "Handsfree got agent answer (turn %d/%d) | tool=%s answer: %s",
                        dialog_turn + 1, max_dialog_turns, tool_name, agent_answer,
                    )

                    # 将Agent的回答追加到 messages，下一轮循环重新审批
                    current_messages.append({"role": "assistant", "content": resp_content or ""})
                    from system.templates import read_template
                    current_messages.append({
                        "role": "user",
                        "content": read_template("approval/dialog_re_evaluate.txt")
                            .replace("{{dialog_turn}}", str(dialog_turn + 1))
                            .replace("{{ask_question}}", ask_question)
                            .replace("{{agent_answer}}", agent_answer),
                    })
                    messages.extend(current_messages[2:])  # 保留 system + 原始 user，追加对话
                    dialog_turn += 1
                    break  # 跳出重试循环，进入 while 下一轮

                # Process approve / deny
                approved: bool = result["approved"]
                reason_text = cast(str, result.get("reason", ""))
                if approved:
                    logger.info("Handsfree approved | tool=%s reason=%s", tool_name, reason_text)
                    return ApprovalResult(action="allow_once")
                logger.info("Handsfree denied | tool=%s reason=%s", tool_name, reason_text)
                return ApprovalResult(action="deny", deny_reason=reason_text or "Security review failed", denied_by="model")

            except Exception as exc:
                last_error = str(exc)
                resp_content = locals().get("resp_content", "<not available>")
                logger.warning(
                    "Handsfree approval attempt %d/%d failed: %s | resp=%r",
                    attempt, LLM_RETRY_COUNT, exc, resp_content,
                )
                if attempt < LLM_RETRY_COUNT:
                    _ct = (get_templates_dir() / "approval" / "correction_hint.md").read_text(encoding="utf-8")
                    current_messages.append({
                        "role": "user",
                        "content": _ct.replace("{{error}}", str(exc)).replace("{{raw_output}}", resp_content or "<not available>"),
                    })

        # 重试循环全部失败 → 退出 while，最终返回 deny
        if last_error:
            break

    logger.warning(
        "Handsfree approval exhausted — denying tool=%s | last_error=%s",
        tool_name, last_error,
    )
    return ApprovalResult(
        action="deny",
        deny_reason=f"approval model continuous parsing failed: {last_error}" if last_error else "approval model cannot make a decision",
        denied_by="approval model",
    )