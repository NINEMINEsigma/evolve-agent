"""Compress complete tool chains while preserving conversation rounds."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, TYPE_CHECKING

from abstract.tools.registry import ToolRegistry, tool_error, tool_result
from abstract.tools.ui_event_router import UIEventRouter
from component.tools._history_compression import prepare_tool_chain_replacements
from entity.constant import COMPRESSED_TOOL_CHAIN_CALL_NAME, TOOL_CHAIN_COMPRESS_MIN_CHARS
from entity.puretype import ToolAvailability, ToolDangerLevel

if TYPE_CHECKING:
    from entry.base_agent_loop import ToolContext

logger = logging.getLogger(__name__)


async def _handle_compress_tool_chains(
    args: dict[str, Any], context: ToolContext,
) -> dict:
    """Summarize complete chains before applying and persisting any replacements."""
    from system.session_metadata import SessionMetadataError, SessionMetadataService

    del args  # 此工具不接收业务参数；注册表仍可能注入内部字段。
    loop = context.loop
    session_id = context.session_id
    history = loop.history
    snapshot = list(history.iter_messages())
    metadata_service = context.app.get_system(SessionMetadataService)

    try:
        replacements = await prepare_tool_chain_replacements(
            snapshot, session_id=session_id, metadata_service=metadata_service,
        )
    except SessionMetadataError as exc:
        return tool_error(f"Tool chain summary generation failed: {exc}")

    # 生成期间收到的协作式中断也必须在提交前生效；取消不转换为成功。
    if context.is_interrupted:
        raise asyncio.CancelledError

    if not replacements:
        return tool_result(
            success=True,
            tool_chains_compressed=0,
            messages_removed=0,
            remaining=history.count,
        )

    messages_removed = sum(
        replacement.end - replacement.start - len(replacement.messages)
        for replacement in replacements
    )
    # 全部摘要准备完毕才修改；同步替换与保存之间不引入取消点。
    # 不清理未配对调用，本次工具调用的结果尚未写入 History。
    for replacement in reversed(replacements):
        history.replace_range(replacement.start, replacement.end, replacement.messages)
    loop.save_history(session_id)
    loop.reset_context_tokens()

    await context.sink.emit_system_message(session_id, "Tool chain compression complete")
    logger.info(
        "Tool chains compressed | session=%s chains=%d messages_removed=%d remaining=%d",
        session_id, len(replacements), messages_removed, history.count,
    )
    return tool_result(
        success=True,
        tool_chains_compressed=len(replacements),
        messages_removed=messages_removed,
        remaining=history.count,
    )


_COMPRESS_TOOL_CHAINS_SCHEMA = {
    # 只压缩全部历史中的完整工具链，不截断轮次、不要求会话摘要。
    # 用户消息与不带 tool_calls 的普通回复保持原样；工具链内正文会进入链摘要。
    # 纯压缩占位链跳过，模型摘要全部准备成功后才替换并保存。
    # critical 在手动/脱手模式由用户审批，YOLO 模式免审批。
    "description": f"""Compress complete tool chains across the current conversation history without removing conversation rounds or replacing ordinary dialogue with a session summary.

## Prerequisites
- A complete tool chain must contain real tool calls, have results for every call, and reach {TOOL_CHAIN_COMPRESS_MIN_CHARS} characters of original content and arguments.
- Summaries use the global toolchain summary Profile, or the target session's active Profile when that global selection is unset.
- No arguments or conversation summary are required.

## Effect
1. Scan the entire current session history, not just recent rounds.
2. Replace each eligible chain with one `{COMPRESSED_TOOL_CHAIN_CALL_NAME}` placeholder call (not callable) and its paired model-generated summary result.
3. Preserve user messages, system messages, and assistant replies without tool calls. Assistant text inside a tool chain is summarized with that chain.
4. Leave incomplete chains, including the chain containing this invocation, unchanged. Skip chains containing only compressed placeholder calls; chains with new real calls remain eligible.
5. Generate all summaries before modifying history. A summary failure or cancellation during generation applies no compression changes.
6. If no chain is eligible, return success with zero counts without modifying history or calling a model.

## Returns
`success`, `tool_chains_compressed` (number of replaced chains), `messages_removed` (net reduction in History messages), and `remaining` (History message count before this tool's result is appended).

## When to Use
- When tool output occupies too much context but the user wants the conversation itself retained.
- When the user asks to compress only tool chains.
- Use CompressHistory instead when older conversation rounds should also be replaced by a session summary.

## Side Effects
- Compression is irreversible: original tool requests and results, including media in those chains, are replaced by summaries.
- One model request per eligible chain may incur time and cost. There is no tool execution timeout; user interruption remains available.
- This is a critical operation: manual and handsfree modes require user approval; YOLO mode bypasses approval.
- Successful compression persists History and invalidates the previous prompt token count. Persistence failures propagate and are not reported as success.""",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


def register_tools(registry: ToolRegistry, ui_events: UIEventRouter) -> None:
    """Register the tool-chain-only compression tool."""
    del ui_events  # 沿用现有系统消息通知，不新增 UI 事件路由。
    registry.register(
        name="CompressToolChains",
        toolset="core",
        schema=_COMPRESS_TOOL_CHAINS_SCHEMA,
        handler=_handle_compress_tool_chains,
        is_async=True,
        danger_level=ToolDangerLevel.critical,
        availability=ToolAvailability.MAIN,
        no_timeout=True,
    )
