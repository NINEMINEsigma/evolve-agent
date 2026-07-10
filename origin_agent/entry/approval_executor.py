"""ApprovalExecutor — 统一审批执行器。

提取 parent_agent_loop.py 与 multi_agent_loop.py 中重复的审批逻辑，
提供纯函数 `execute_with_approval`，封装 dangerous/write 判断、白名单检查、
脱手/正常两种审批模式、拒绝结果构建和 allow_always 加白名单。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from abstract.tools.registry import registry as tool_registry
from component.approval import ApprovalResult, is_handsfree_mode, request_user_confirm
from component.approval_allowlist import add_allowed as add_tool_allowlist_entry
from component.approval_allowlist import is_allowed as is_tool_allowlisted
from entity.puretype import ApprovalOutcome, ToolDangerLevel

if TYPE_CHECKING:
    from entry.agent_sink import AgentSink

logger = logging.getLogger(__name__)


def _build_approval_content(tool_name: str, approval_args: dict) -> str:
    """构建审批请求的描述文本。"""
    params = json.dumps(approval_args, ensure_ascii=False)
    return f"Tool: {tool_name}\nParameters: {params}"


def _build_deny_result(approval: ApprovalResult) -> dict:
    """根据 ApprovalResult 构建统一的 deny 错误 dict。"""
    source_label = {"model": "approval model", "user": "user", "system": "system"}.get(
        approval.denied_by, "system"
    )
    return {
        "error": f"[{source_label} denied] {approval.deny_reason or 'unknown reason'}",
        "denied": True,
        "denied_by": approval.denied_by,
    }


def _needs_approval(tool_name: str, session_id: str) -> bool:
    """判断工具是否需要审批。

    - dangerous 级别始终需要
    - write 级别仅在脱手模式下需要
    - readonly/safe 直接执行
    """
    danger_level: ToolDangerLevel = tool_registry.get_danger_level(tool_name)
    handsfree = is_handsfree_mode(session_id)
    return danger_level == ToolDangerLevel.dangerous or (
        danger_level == ToolDangerLevel.write and handsfree
    )


async def execute_with_approval(
    tool_name: str,
    args: dict,
    session_id: str,
    *,
    sink: AgentSink,
    ask_agent_callback: Callable[[str], Awaitable[str]] | None = None,
    hooks_context: str = "",
) -> ApprovalOutcome:
    """统一的工具审批流程。

    封装 dangerous/write 判断、白名单检查、脱手/正常两种审批模式、
    拒绝结果构建和 allow_always 加白名单的全部逻辑。

    Args:
        tool_name: 工具名称。
        args: 工具参数 dict（审批通过后会原地修改，加入 _pre_approved / _approval_action）。
        session_id: 会话 ID。
        sink: AgentSink 实例，用于正常模式通过前端请求审批。
        ask_agent_callback: 脱手模式下审批模型向主模型提问的回调。
                           仅父 Agent 需要传入（multi loop 中脱手模式不使用）。
        hooks_context: 脱手模式下注入审批请求的 hooks 上下文。

    Returns:
        ApprovalOutcome:
            - denied=True 时，deny_result 包含错误信息，调用方应跳过工具分发。
            - denied=False 时，args 已被原地修改（_pre_approved / _approval_action），调用方继续分发。
    """
    # 不需要审批的工具：直接放行
    if not _needs_approval(tool_name, session_id):
        return ApprovalOutcome(denied=False, approved_args=args)

    # 构建审批用参数（去除内部 _session_id）
    approval_args = {k: v for k, v in args.items() if k != "_session_id"}

    # 白名单检查：匹配则跳过审批，直接允许
    if is_tool_allowlisted(tool_name, approval_args):
        args["_pre_approved"] = True
        args["_approval_action"] = "allow_once"
        return ApprovalOutcome(denied=False, approved_args=args)

    # 请求审批
    handsfree = is_handsfree_mode(session_id)
    approval: ApprovalResult

    if handsfree:
        # 脱手模式：通过 approval 模型（本地/远程）自动审批
        # 若未提供回调，使用空回调兜底
        async def _empty_callback(_q: str) -> str:
            return ""

        _callback = ask_agent_callback or _empty_callback
        approval = await request_user_confirm(
            session_id, tool_name, approval_args,
            reason=str(args.get("reason", "")),
            content=_build_approval_content(tool_name, approval_args),
            ask_agent_callback=_callback,
            extra_context=hooks_context if hooks_context else None,
        )
    else:
        # 正常模式：通过 AgentSink 请求前端用户审批
        approval = await sink.request_approval(
            tool_name=tool_name,
            args=approval_args,
            reason=str(args.get("reason", "")),
            content=_build_approval_content(tool_name, approval_args),
            session_id=session_id,
        )

    # 拒绝
    if approval.action == "deny":
        return ApprovalOutcome(
            denied=True,
            deny_result=_build_deny_result(approval),
            approved_args=args,
        )

    # 允许：非脱手模式的 allow_always 加入白名单
    if approval.action == "allow_always" and not handsfree:
        add_tool_allowlist_entry(tool_name, approval_args)

    args["_pre_approved"] = True
    args["_approval_action"] = approval.action
    return ApprovalOutcome(denied=False, approved_args=args)