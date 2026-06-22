"""审批子 Agent 的工具调用。

模块导入时通过 ``registry.register()`` 注册 ``approval_subagent`` 工具。
父 Agent 通过此工具批量审批子 Agent 提交的工具调用申请，
同意的工具立即在子 Agent 上下文中执行，拒绝的工具需附带原因。
"""

from __future__ import annotations

from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result


async def _handle_approval_subagent(args: dict[str, Any]) -> dict:
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

    try:
        from gateway.server import get_subagent_orchestrator
        orch = get_subagent_orchestrator()
        result = await orch.approve(session_id, decisions)
        return tool_result(**result)
    except Exception as exc:
        return tool_error(f"Failed to approve subagent tools: {exc}")


registry.register(
    name="approval_subagent",
    toolset="multiagent",
    schema={
        # 批量批准或拒绝子 Agent 的工具调用请求。
        # 批准的工具在子 Agent 上下文中立即执行。
        # 拒绝的工具必须包含原因。
        # 子 Agent 在等待审批期间完全暂停（没有超时）。
        # 返回可选的 'feedback' 字段——子 Agent 发件箱中的文本响应列表，在工具执行后收集。用于即时反馈。
        "description": """Batch approve or reject tool-call requests from a sub-agent. Approved tools execute immediately in the sub-agent context. Rejected tools must include a reason. The sub-agent is fully paused while waiting for approval (there is no timeout).

Returns an optional 'feedback' field — a list of text responses from the sub-agent's outbox collected after tool execution. Use this for instant feedback.""",
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
                                # 子 Agent 发来的工具调用 ID。
                                "description": "The tool call ID from the sub-agent.",
                            },
                            "approved": {
                                "type": "boolean",
                                # 是否批准此工具调用。
                                "description": "Whether to approve this tool call.",
                            },
                            "reason": {
                                "type": "string",
                                # 拒绝原因（approved=false 时必填）。
                                "description": "Reason for denial (required when approved=false).",
                            },
                        },
                        "required": ["tool_call_id", "approved"],
                    },
                    # 审批决策列表。每个条目批准或拒绝子 Agent 的一个工具调用。
                    "description": "List of approval decisions. Each entry approves or rejects one tool call from the sub-agent.",
                },
            },
            "required": ["session_id", "decisions"],
        },
    },
    handler=_handle_approval_subagent,
    is_async=True,
    emoji="✅",
    danger_level="readonly",
)