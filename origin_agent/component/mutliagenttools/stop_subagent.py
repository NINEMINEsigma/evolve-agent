"""停止子 Agent 会话。

模块导入时通过 ``registry.register()`` 注册 ``stop_subagent`` 工具。
父 Agent 通过此工具强制终止指定子 Agent 会话，
落盘完整会话历史，并可能激活等待队列中的下一个子 Agent。
"""

from __future__ import annotations

from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result


def _handle_stop_subagent(args: dict[str, Any]) -> dict:
    """停止子 Agent 会话。

    预期参数：
        session_id: str — 要停止的子 Agent 会话 ID

    返回值：
        success:      bool — 是否成功
        session_path: str  — 会话历史文件路径
        promoted:     list — 因停止而被激活的等待子 Agent（一出一入，最多一个）
    """
    session_id: str = str(args.get("session_id", "")).strip()

    if not session_id:
        return tool_error("'session_id' is required and must not be empty")

    # TODO: 实现停止逻辑
    # 1. 通过编排器查找 session_id 对应的位置（活跃表或等待队列）
    # 2. 若在等待队列中 → 直接移出队列，不保存会话（无历史），返回 success=true, session_path=null
    # 3. 若在活跃表中：
    #    a. 检查子 Agent 是否已完成（已完成则返回失败）
    #    b. 取消当前 LLM 调用，丢弃所有待审批工具调用
    #    c. 将完整会话历史写入 workspace/logs/subagents/{session_id}.jsonl
    #    d. 如果等待队列非空，取出头部一个子 Agent 启动
    # 4. 返回停止结果和被激活的会话信息

    return tool_result(
        success=True,
        session_id=session_id,
        message="Stop request validated. Execution not yet implemented.",
    )


registry.register(
    name="stop_subagent",
    toolset="multiagent",
    schema={
        # 强制终止一个子 Agent 会话。每次仅停止一个子 Agent。
        # 停止后完整会话历史保存到 workspace/logs/subagents/ 下的 JSONL 文件。
        # 已完成的子 Agent 无法再次停止。
        # 若等待队列非空，停止后自动激活队列头部的一个子 Agent（一出一入）。
        "description": (
            "Forcefully terminate a sub-agent session. "
            "Only one sub-agent can be stopped per call. "
            "The complete session history is saved as a JSONL file. "
            "An already-completed sub-agent cannot be stopped again. "
            "If the waiting queue is non-empty, the next queued sub-agent is "
            "automatically activated after this one is stopped."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    # 要停止的子 Agent 会话 ID。
                    "description": "Session ID of the sub-agent to stop.",
                },
            },
            "required": ["session_id"],
        },
    },
    handler=_handle_stop_subagent,
    emoji="🛑",
    danger_level="write",
)