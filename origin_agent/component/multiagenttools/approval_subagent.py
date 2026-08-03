"""审批子 Agent 的工具调用。

模块导入时通过 ``registry.register()`` 注册 ``approval_subagent`` 工具。
父 Agent 通过此工具批量审批子 Agent 提交的工具调用申请，
同意的工具立即在子 Agent 上下文中执行，拒绝的工具需附带原因。
"""

from __future__ import annotations

from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result
from entity.puretype import ToolAvailability, ToolDangerLevel


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

    parent_session_id: str = str(args.get("_session_id", "")).strip()
    if not parent_session_id:
        return tool_error("'_session_id' is required and must not be empty")

    try:
        from system.application import Application
        orch = Application.current().subagent_orchestrator
        result = await orch.approve(parent_session_id=parent_session_id, session_id=session_id, decisions=decisions)
        return tool_result(**result)
    except Exception as exc:
        return tool_error(f"Failed to approve subagent tools: {exc}")


registry.register(
    name="approval_subagent",
    toolset="multiagent",
    schema={
        # 批量批准或拒绝子 Agent 的工具调用请求。
        #
        # ## 前置条件
        # 子 Agent 必须处于等待审批状态（已发起一个或多个需要审批的工具调用）。
        # 必须清楚了解每个待审批工具调用的参数和潜在影响后再做决定。
        # 同一个 tool_call_id 不要重复审批；提交前确认列表中没有已处理过的调用。
        #
        # ## 调用效果
        # 批准的工具会立即在子 Agent 上下文中执行；拒绝的工具不会执行，并且子 Agent 会收到拒绝原因。
        # 子 Agent 在等待审批期间完全暂停，没有超时。
        # 每次调用只能处理一个 session_id 的审批请求。
        #
        # ## 返回
        # ```json
        # {"feedback": ["..."], "success": true}
        # ```
        # feedback 是子 Agent 发件箱中在当前工具执行后收集的文本响应列表，可用于即时反馈。
        #
        # ## 何时使用
        # - 子 Agent 的工具调用请求需要父 Agent 审批时。
        # - 需要批量处理多个待审批工具调用时。
        #
        # ## 副作用/注意
        # - 批准 dangerous 或 write 级别工具可能导致不可逆的系统变更。
        # - 拒绝时必须提供 reason，否则调用会失败。
        # - 审批期间子 Agent 完全冻结，不会产生新输出。
        # - 不要对同一个 tool_call_id 重复提交审批，否则可能导致执行异常或状态混乱。
        "description": """Batch approve or reject tool-call requests from a sub-agent.

## Prerequisites
The sub-agent must be in a waiting-for-approval state (it has issued one or more tool calls that require approval).
You MUST understand each pending tool call's arguments and potential impact before deciding.
Do NOT approve or reject the same tool_call_id more than once. Confirm that none of the entries have already been handled before submitting.

## Effect
Approved tools execute immediately in the sub-agent context. Rejected tools do not execute, and the sub-agent receives the rejection reason.
The sub-agent is fully paused while waiting for approval; there is no timeout.
Each call handles pending requests for exactly one session_id.

## Returns
```json
{"feedback": ["..."], "success": true}
```
The optional 'feedback' field is a list of text responses from the sub-agent's outbox collected after the executed tools, useful for instant feedback.

## When to Use
- When a sub-agent's tool call requests require parent-agent approval.
- When you need to approve or reject multiple pending tool calls at once.

## Side Effects / Notes
- Approving dangerous or write-level tools may cause irreversible system changes.
- Rejection MUST include a reason; otherwise the call fails.
- The sub-agent is completely frozen during approval and produces no new output.
- Do not submit duplicate decisions for the same tool_call_id; this may cause execution anomalies or inconsistent state.""",
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
                                # 拒绝原因。当 approved=false 时必填。
                                "description": """Reason for denial. Required when approved=false.""",
                            },
                        },
                        "required": ["tool_call_id", "approved"],
                    },
                    # 审批决策列表。每个条目批准或拒绝子 Agent 的一个工具调用。拒绝时 reason 必填。
                    "description": """List of approval decisions. Each entry approves or rejects one tool call from the sub-agent. reason is required for rejected entries.""",
                },
            },
            "required": ["session_id", "decisions"],
        },
    },
    handler=_handle_approval_subagent,
    is_async=True,
    emoji="✅",
    danger_level=ToolDangerLevel.readonly,
    availability=ToolAvailability.MAIN,
)