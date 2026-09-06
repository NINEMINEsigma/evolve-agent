"""脱手模式状态与普通文本审批决策。"""

from __future__ import annotations

import json
import logging
from typing import Any

from entity.constant import (
    APPROVAL_ALLOW_MARKERS,
    APPROVAL_DENY_MARKERS,
    SYSTEM_CHARACTER_NAME,
)
from entity.messages import BaseMessage
from entity.puretype import ApprovalResult, ApprovalMode, Role

logger = logging.getLogger(__name__)


_approval_modes: dict[str, ApprovalMode] = {}


def is_handsfree_available() -> bool:
    """返回项目级审批 Profile 是否已配置且具备必需连接字段。"""
    try:
        from system.application import Application

        manager = Application.current().approval_backend_manager
        return manager is not None and manager.get_backend() is not None
    except Exception:
        logger.debug("Failed to resolve handsfree availability", exc_info=True)
        return False


def set_approval_mode(session_id: str, mode: ApprovalMode) -> ApprovalMode:
    """设置会话审批模式并返回服务端实际状态。

    HANDSFREE 模式在审批模型不可用时回退为 MANUAL。
    """
    if mode == ApprovalMode.HANDSFREE and not is_handsfree_available():
        actual = ApprovalMode.MANUAL
    else:
        actual = mode
    _approval_modes[session_id] = actual
    logger.info(
        "Approval mode set | session=%s mode=%s actual=%s",
        session_id, mode.value, actual.value,
    )
    return actual


def get_approval_mode(session_id: str) -> ApprovalMode:
    """返回该会话当前的审批模式（默认 MANUAL）。"""
    return _approval_modes.get(session_id, ApprovalMode.MANUAL)


def disable_all_non_manual_modes() -> list[str]:
    """将全部非 MANUAL 的会话重置为 MANUAL，返回受影响的 session ID。"""
    disabled = sorted(
        session_id
        for session_id, mode in _approval_modes.items()
        if mode != ApprovalMode.MANUAL
    )
    for session_id in disabled:
        _approval_modes[session_id] = ApprovalMode.MANUAL
    if disabled:
        logger.info("Reset non-manual approval modes for sessions=%s", disabled)
    return disabled


# ---- 向后兼容包装 ----

def set_handsfree_mode(session_id: str, enabled: bool) -> bool:
    """兼容包装：设置脱手模式。等价于 set_approval_mode(sid, HANDSFREE/MANUAL)。"""
    mode = ApprovalMode.HANDSFREE if enabled else ApprovalMode.MANUAL
    return set_approval_mode(session_id, mode) == ApprovalMode.HANDSFREE


def is_handsfree_mode(session_id: str) -> bool:
    """兼容包装：返回该会话是否处于脱手模式。"""
    return get_approval_mode(session_id) == ApprovalMode.HANDSFREE


def disable_all_handsfree_modes() -> list[str]:
    """兼容包装：关闭全部脱手模式会话。等价于 disable_all_non_manual_modes()。"""
    return disable_all_non_manual_modes()


def _approval_model_failure(reason: str) -> ApprovalResult:
    """把审批模型失效转换为闭合失败，并指示调用方停止工具链。"""
    detail = reason.strip() or "unavailable"
    return ApprovalResult(
        action="deny",
        deny_reason=(
            f"Approval model unavailable ({detail}). Stop the current tool-call chain, "
            "report that the approval model has failed, and ask the user to turn off "
            "handsfree mode. Do not call more tools in this turn."
        ),
        denied_by=SYSTEM_CHARACTER_NAME,
    )


def _interpret_approval_response(content: str) -> ApprovalResult:
    """按否定优先的显式文本标记解释审批模型响应。"""
    response = content.strip()
    if not response:
        return _approval_model_failure("empty response")

    normalized = response.casefold()
    if any(marker in normalized for marker in APPROVAL_DENY_MARKERS):
        return ApprovalResult(
            action="deny",
            deny_reason=response,
            denied_by="model",
        )
    if any(marker in normalized for marker in APPROVAL_ALLOW_MARKERS):
        return ApprovalResult(action="allow_once", denied_by="")
    return _approval_model_failure("missing decision marker")


async def _handsfree_confirm(
    tool_name: str,
    args: dict,
    reason: str,
    extra_context: str | None = None,
) -> ApprovalResult:
    """把工具调用发送给审批 Profile，并解释单次普通文本响应。"""
    try:
        from system.application import Application

        manager = Application.current().approval_backend_manager
        backend = manager.get_backend() if manager is not None else None
    except Exception:
        logger.warning("Failed to resolve approval backend", exc_info=True)
        return _approval_model_failure("backend resolution failed")

    if backend is None:
        logger.warning("Approval backend unavailable — handsfree mode deny")
        return _approval_model_failure("backend unavailable")

    from system.application import Application as _App
    _approval_profile = _App.current().llm_profile_store.get_approval_profile()
    logger.info(
        "Approval model request | tool=%s profile=%s model=%s",
        tool_name,
        _approval_profile.name if _approval_profile else None,
        _approval_profile.model if _approval_profile else None,
    )

    from system.pathutils import get_templates_dir

    # 获取工具的参数 schema，使审批模型能理解每个参数的类型、描述、
    # 默认值和是否必填，从而区分"必需信息缺失"与"可选参数省略"。
    from abstract.tools.registry import registry as tool_registry
    tool_schema = tool_registry.get_schema(tool_name)

    system_prompt = (
        get_templates_dir() / "approval" / "system_prompt.md"
    ).read_text(encoding="utf-8")
    user_prompt_data: dict[str, Any] = {
        "tool": tool_name,
        "schema": tool_schema,
        "args": args,
        "reason": reason,
    }
    if extra_context:
        user_prompt_data["context"] = extra_context

    messages = [
        BaseMessage(role=Role.SYSTEM, content=system_prompt),
        BaseMessage(
            role=Role.USER,
            content=json.dumps(user_prompt_data, ensure_ascii=False),
        ),
    ]
    try:
        response = await backend.chat(messages)
    except Exception:
        logger.warning(
            "Approval model request failed | tool=%s",
            tool_name,
            exc_info=True,
        )
        return _approval_model_failure("request failed")

    logger.debug("Approval model response | tool=%s response=%s", tool_name, response)
    result = _interpret_approval_response(response)
    if result.action == "deny":
        logger.info(
            "Handsfree denied | tool=%s denied_by=%s reason=%s",
            tool_name,
            result.denied_by,
            result.deny_reason,
        )
    else:
        logger.info("Handsfree approved | tool=%s response=%s", tool_name, response)
    return result