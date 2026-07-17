"""工具执行 post-dispatch 共享函数。

提取 ToolExecutor.execute 与 SubAgentLoop._execute_approved_tool 中重复的后处理逻辑：
构建 ToolCallMeta、注入 _meta、推送前端 tool_result 事件、路由 UI 事件，
最终返回可存入 History 的 ToolResultMessage。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from entity.puretype import Role, ToolCallMeta
from entity.messages import ToolResultMessage
from entry.agent_support.multimodal import tool_result_to_content, content_to_text
from abstract.tools.ui_event_router import ui_event_router

if TYPE_CHECKING:
    from entry.agent_sink import AgentSink

logger = logging.getLogger(__name__)


async def finalize_tool_result(
    result: dict | str,
    *,
    tool_name: str,
    application_time: str,
    application_time_ms: int,
    approval_duration_ms: int,
    invocation_start_offset_ms: int,
    invocation_duration_ms: int,
    end_time_offset_ms: int,
    sink: "AgentSink",
    session_id: str,
    tool_call_id: str,
    character_name: str,
) -> ToolResultMessage:
    """构建 _meta、注入到结果、推送前端事件和 UI 事件，返回 ToolResultMessage。

    供 ToolExecutor.execute 和 SubAgentLoop._execute_approved_tool 共享调用。
    所有时间戳参数由调用方在 dispatch 前后记录并传入。

    Args:
        result: 工具 handler 返回的原始结果（dict 或 str）。
        tool_name: 工具名称。
        application_time: 人类可读的申请时间字符串。
        application_time_ms: 申请时间的绝对毫秒时间戳。
        approval_duration_ms: 审批耗时（毫秒），无需审批时为 0。
        invocation_start_offset_ms: 从申请到开始调用 handler 的毫秒偏移。
        invocation_duration_ms: handler 实际执行的毫秒数。
        end_time_offset_ms: 从申请到工具调用完成的毫秒偏移。
        sink: AgentSink 实例，用于推送前端事件。
        session_id: 当前会话 ID。
        tool_call_id: 工具调用 ID。
        character_name: 发起工具调用的角色名。

    Returns:
        可存入 History 的 ToolResultMessage，content 已转换为可序列化格式。
    """
    # 构建 _meta
    _meta = ToolCallMeta(
        application_time=application_time,
        application_time_ms=application_time_ms,
        approval_duration_ms=approval_duration_ms,
        invocation_start_offset_ms=invocation_start_offset_ms,
        invocation_duration_ms=invocation_duration_ms,
        end_time_offset_ms=end_time_offset_ms,
    )

    # 注入 _meta 到结果
    if isinstance(result, dict):
        result["_meta"] = _meta.model_dump()
    else:
        result = {"result": result, "_meta": _meta.model_dump()}

    # 转换为可保存到 History 的 content
    content = tool_result_to_content(result)

    # 推送前端 tool_result 事件（使用文本摘要，避免 base64 撑爆前端事件）
    await sink.emit_tool_result(
        session_id, tool_name, tool_call_id, content_to_text(content),
        character_name=character_name,
        tool_call_meta=_meta.model_dump(),
    )

    # 对前端 UI 类工具推送实时状态更新（工具模块自行注册事件类型）
    await ui_event_router.emit_for(
        tool_name,
        result,
        sink,
        session_id,
    )

    return ToolResultMessage(
        role=Role.TOOL,
        character_name=character_name,
        tool_call_id=tool_call_id,
        content=content,
    )