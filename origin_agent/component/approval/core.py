"""审批流程统一入口与拒绝工具结果构造。"""

from __future__ import annotations

from typing import Any

from entity.constant import SYSTEM_CHARACTER_NAME
from entity.puretype import ApprovalResult


async def request_user_confirm(
    session_id: str,
    tool_name: str,
    args: dict,
    reason: str,
    content: str,
    extra_context: str | None = None,
) -> ApprovalResult:
    """按会话模式分流到审批 Profile 或前端人工审批。"""
    from component.approval.handsfree import _handsfree_confirm, is_handsfree_mode

    if is_handsfree_mode(session_id):
        return await _handsfree_confirm(
            tool_name,
            args,
            reason,
            extra_context=extra_context,
        )

    from system.application import Application

    return await Application.current().frontend_sink.request_approval(
        tool_name=tool_name,
        args=args,
        reason=reason,
        content=content,
        session_id=session_id,
    )


def build_denied_tool_result(approval: ApprovalResult) -> dict[str, Any]:
    """按拒绝来源构建所有 Loop 共用的工具结果。"""
    source_label = {
        "model": "approval model",
        "user": "user",
        "parent_agent": "parent Agent",
        SYSTEM_CHARACTER_NAME: SYSTEM_CHARACTER_NAME,
    }.get(approval.denied_by, SYSTEM_CHARACTER_NAME)
    return {
        "error": f"[{source_label} denied] {approval.deny_reason or 'unknown reason'}",
        "denied": True,
        "denied_by": approval.denied_by or SYSTEM_CHARACTER_NAME,
    }