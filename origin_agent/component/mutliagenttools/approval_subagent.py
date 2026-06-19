"""审批子 Agent 的工具调用。

模块导入时通过 ``registry.register()`` 注册 ``approval_subagent`` 工具。
父 Agent 通过此工具批量审批子 Agent 提交的工具调用申请，
同意的工具立即在子 Agent 上下文中执行，拒绝的工具需附带原因。
"""

from __future__ import annotations

from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result


def _handle_approval_subagent(args: dict[str, Any]) -> dict:
    """审批子 Agent 的工具调用。

    预期参数：
        session_id: str — 目标子 Agent 会话 ID
        decisions:  list[dict] — 审批决策列表，每项包含：
            tool_call_id: str   — 待审批的工具调用 ID
            approved:     bool  — 是否同意
            reason:       str   — 拒绝时提供原因（approved=false 时必填）
    """
    session_id: str = str(args.get("session_id", "")).strip()
    raw_decisions: Any = args.get("decisions")

    if not session_id:
        return tool_error("'session_id' is required and must not be empty")
    if raw_decisions is None:
        return tool_error("'decisions' is required")
    if not isinstance(raw_decisions, list) or len(raw_decisions) == 0:
        return tool_error("'decisions' must be a non-empty list")

    decisions: list[dict[str, Any]] = []
    for i, d in enumerate(raw_decisions):
        if not isinstance(d, dict):
            return tool_error(f"decisions[{i}] must be an object")
        tool_call_id = str(d.get("tool_call_id", "")).strip()
        if not tool_call_id:
            return tool_error(f"decisions[{i}].tool_call_id is required")
        if "approved" not in d:
            return tool_error(f"decisions[{i}].approved is required")
        approved = bool(d["approved"])
        reason = str(d.get("reason", "")).strip()
        if not approved and not reason:
            return tool_error(f"decisions[{i}].reason is required when approved=false")
        decisions.append({
            "tool_call_id": tool_call_id,
            "approved": approved,
            "reason": reason if not approved else None,
        })

    # TODO: 实现批量审批逻辑
    # 1. 通过编排器查找 session_id 对应的 SubAgentLoop
    # 2. 按其待审批队列匹配 tool_call_id
    # 3. 同意的工具立即在子 Agent 上下文中执行，结果注入
    # 4. 拒绝的工具将原因返回给子 Agent
    # 5. 所有决策处理完后解除子 Agent 阻塞

    return tool_result(
        success=True,
        session_id=session_id,
        processed=len(decisions),
        message="Approval decisions validated. Execution not yet implemented.",
    )


registry.register(
    name="approval_subagent",
    toolset="multiagent",
    schema={
        # 批量审批子 Agent 的工具调用申请。
        # 同意的工具立即执行，拒绝的工具必须附带原因。
        # 子 Agent 的工具调用永不超时，等待父 Agent 审批期间完全暂停。
        "description": (
            "Batch approve or reject tool-call requests from a sub-agent. "
            "Approved tools execute immediately in the sub-agent context. "
            "Rejected tools must include a reason. "
            "The sub-agent is fully paused while waiting for approval "
            "(there is no timeout)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    # 目标子 Agent 的会话 ID。
                    "description": "Session ID of the target sub-agent.",
                },
                "decisions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool_call_id": {
                                "type": "string",
                                # 子 Agent 发出的工具调用 ID。
                                "description": "The tool call ID from the sub-agent.",
                            },
                            "approved": {
                                "type": "boolean",
                                # 是否同意执行。
                                "description": "Whether to approve this tool call.",
                            },
                            "reason": {
                                "type": "string",
                                # 拒绝原因（拒绝时必填）。
                                "description": "Reason for denial (required when approved=false).",
                            },
                        },
                        "required": ["tool_call_id", "approved"],
                    },
                    # 审批决策列表，一次调用可审批多个工具调用。
                    "description": "List of approval decisions. Each entry approves or rejects one tool call from the sub-agent.",
                },
            },
            "required": ["session_id", "decisions"],
        },
    },
    handler=_handle_approval_subagent,
    emoji="✅",
    danger_level="readonly",
)