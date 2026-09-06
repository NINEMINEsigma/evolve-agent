"""工具执行 post-dispatch 共享函数。

提取 ToolExecutor.execute 与 SubAgentLoop._execute_approved_tool 中重复的后处理逻辑：
构建 ToolCallMeta、注入 _meta、推送前端 tool_result 事件、路由 UI 事件，
最终返回可存入 History 的 ToolResultMessage。
"""

from __future__ import annotations

import logging
from typing import Callable, TYPE_CHECKING

from entity.puretype import Role, ToolCallMeta
from entity.messages import BaseMessage, ToolResultMessage
from entry.agent_support.multimodal import tool_result_to_content, tool_result_to_follow_up, content_to_text
from abstract.tools.ui_event_router import ui_event_router

if TYPE_CHECKING:
    from entry.agent_sink import AgentSink

logger = logging.getLogger(__name__)

# 工具结果字段注入器：接收已注入 _meta 的 result dict，
# 返回要合并到 result 的字段 dict（或 None 表示无注入）。
# SP-4 的 SessionMessageQueue.drain() 将实现此接口。
ResultFieldInjector = Callable[[dict], dict | None]


async def finalize_tool_result(
    result: dict,
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
    field_injector: ResultFieldInjector | None = None,
) -> ToolResultMessage:
    """构建 _meta、注入到结果、推送前端事件和 UI 事件，返回 ToolResultMessage。

    供 ToolExecutor.execute 和 SubAgentLoop._execute_approved_tool 共享调用。
    所有时间戳参数由调用方在 dispatch 前后记录并传入。

    Args:
        result: 工具 handler 返回的原始结果。
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
    result["_meta"] = _meta.model_dump()

    # SP-2: 结果字段注入——由 ToolExecutor 从所属 loop 的队列对象获取注入器，
    # 队列对象本身不进 finalize（R1）。注入器返回要合并的字段 dict（或 None）。
    # 注入字段在 _meta 之后、tool_result_to_content 之前写入，
    # 随 JSON 自然进入历史持久化、wire 输出与前端展示。
    if field_injector is not None:
        try:
            injected = field_injector(result)
            if isinstance(injected, dict) and injected:
                result.update(injected)
        except Exception:
            logger.warning(
                "field_injector failed for tool=%s session=%s",
                tool_name, session_id, exc_info=True,
            )

    # 转换为可保存到 History 的 content
    # 提取被工具链消费的用户消息 client_message_id 列表（由 drain_injected 通过
    # field_injector 注入），pop 出 result 以确保不进入 content（不进历史/不进 LLM）。
    consumed_ids: list[str] | None = result.pop("consumed_client_message_ids", None)
    # 检查是否需要 follow_up（user 消息多模态回退路径）
    follow_up_messages: list[BaseMessage] | None = None
    if isinstance(result, dict) and "_user_blocks" in result:
        follow_up_messages, content = tool_result_to_follow_up(result, character_name)
    else:
        content = tool_result_to_content(result)

    # 推送前端 tool_result 事件（content_to_text 内部过滤 _ 前缀字段，避免 base64 撑爆前端）
    await sink.emit_tool_result(
        session_id, tool_name, tool_call_id, content_to_text(content),
        character_name=character_name,
        tool_call_meta=_meta.model_dump(),
        consumed_client_message_ids=consumed_ids,
    )

    # 对前端 UI 类工具推送实时状态更新（工具模块自行注册事件类型）
    await ui_event_router.emit_for(
        tool_name,
        result,
        sink,
        session_id,
    )

    tool_result_msg = ToolResultMessage(
        role=Role.TOOL,
        character_name=character_name,
        tool_call_id=tool_call_id,
        content=content,
    )
    tool_result_msg._follow_up_messages = follow_up_messages
    return tool_result_msg