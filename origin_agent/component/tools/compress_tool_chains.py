"""工具链压缩工具 — 仅压缩全部历史中的完整工具链。

工具对象协议：模块导出顶层 ``TOOLSET``（``BaseToolSet``），其中持有
``CompressToolChainsTool`` 实例。``handle`` 不接收业务参数、不含任何历史变更；
真正的扫描、摘要、替换发生在结果写入并保存后的 ``after_handle``——那时本次调用
已经拥有配对结果，全历史扫描因此可以把本次调用自身所在链也纳入压缩（D11）。
"""

from __future__ import annotations

from interface.session_metadata_service import ISessionMetadataService

import asyncio
import logging

from abstract.tools.tool import (
    BaseTool,
    BaseToolSet,
    ToolExecution,
    ToolHandlerResult,
    ToolPostprocessEffect,
    tool_result,
)
from component.tools._history_compression import (
    collect_tool_call_ids,
    prepare_tool_chain_replacements,
)
from entity.constant import COMPRESSED_TOOL_CHAIN_CALL_NAME, TOOL_CHAIN_COMPRESS_MIN_CHARS
from entity.puretype import ToolAvailability, ToolDangerLevel

logger = logging.getLogger(__name__)


_COMPRESS_TOOL_CHAINS_SCHEMA = {
    # 只压缩全部历史中的完整工具链，不截断轮次、不要求会话摘要。
    # 用户消息与不带 tool_calls 的普通回复保持原样；工具链内正文会进入链摘要。
    # 纯压缩占位链跳过，模型摘要全部准备成功后才替换并保存。
    # 本次调用自身所在链在结果提交后已经完整，可一并被压缩（D11）。
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
4. Leave incomplete chains unchanged. Skip chains containing only compressed placeholder calls; chains with new real calls remain eligible. Because this invocation's own result is committed before the scan runs, its own complete chain is eligible and may be compressed together with the rest.
5. Generate all summaries before modifying history. A summary failure or cancellation during generation applies no compression changes.
6. If no chain is eligible, return success with zero counts without modifying history or calling a model.

## Returns
`success`, `tool_chains_compressed` (number of replaced chains), `messages_removed` (net reduction in History messages), and `remaining` (History message count after compression).

## When to Use
- When tool output occupies too much context but the user wants the conversation itself retained.
- When the user asks to compress only tool chains.
- Use CompressHistory instead when older conversation rounds should also be replaced by a session summary.

## Side Effects
- Compression is irreversible: original tool requests and results, including media in those chains, are replaced by summaries.
- One model request per eligible chain may incur time and cost. There is no tool execution timeout; user interruption remains available.
- This is a critical operation: manual and handsfree modes require user approval; YOLO mode bypasses approval.
- Successful compression persists History and invalidates the previous prompt token count. Persistence failures propagate and are not reported as success.
- When this invocation's own chain is compressed, its live tool card is replaced by the chain summary on the frontend.""",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


class CompressToolChainsTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            name="CompressToolChains",
            toolset="core",
            schema=_COMPRESS_TOOL_CHAINS_SCHEMA,
            is_async=True,
            danger_level=ToolDangerLevel.critical,
            availability=ToolAvailability.MAIN,
            no_timeout=True,
            accepts_following_calls=False,
        )

    def handle(self, execution: ToolExecution) -> ToolHandlerResult:
        del execution  # 此工具不接收业务参数；扫描与替换发生在结果提交后的 after。
        return ToolHandlerResult(result=tool_result(success=True, _compression_pending=True))

    async def after_handle(self, execution: ToolExecution) -> ToolPostprocessEffect:
        context = execution.context
        loop = context.loop
        session_id = context.session_id
        history = loop.history

        # 重新取得提交后的完整历史快照：本次调用已有配对结果，可包含自身。
        snapshot = list(history.iter_messages())
        metadata_service = context.app.get_system(ISessionMetadataService)
        replacements = await prepare_tool_chain_replacements(
            snapshot,
            session_id=session_id,
            metadata_service=metadata_service,
            excluded_tool_call_ids=set(),
        )

        # 生成期间收到的协作式中断也必须在提交前生效；取消不转换为成功。
        if context.is_interrupted:
            raise asyncio.CancelledError

        # 无符合条件链：更新已保存结果为零计数，不改历史、不重置计数、不发完成通知。
        if not replacements:
            return ToolPostprocessEffect(
                replacement_result=tool_result(
                    success=True,
                    tool_chains_compressed=0,
                    messages_removed=0,
                    remaining=history.count,
                )
            )

        messages_removed = sum(
            replacement.end - replacement.start - len(replacement.messages)
            for replacement in replacements
        )
        # 被替换链内的真实调用都要从前端移除；仅当自身 ID 在其中时才 suppress。
        discarded_ids = collect_tool_call_ids(
            snapshot,
            [(replacement.start, replacement.end) for replacement in replacements],
        )

        # 全部摘要准备完毕才修改；从后往前替换，同步替换与保存之间不引入取消点。
        for replacement in reversed(replacements):
            history.replace_range(replacement.start, replacement.end, replacement.messages)

        # 保存成功后重置 token 计数并通知完成；任一步失败直接传播。
        loop.save_history(session_id)
        execution.mark_history_updated()
        loop.reset_context_tokens()
        logger.info(
            "Tool chains compressed | session=%s chains=%d messages_removed=%d remaining=%d",
            session_id, len(replacements), messages_removed, history.count,
        )

        # 自身链被替换时其工具结果已离开 History，不能再更新该结果（否则收尾通道
        # 会因找不到消息而失败）；未替换自身时才把占位结果更新为计数结果。
        suppressed = execution.tool_call_id in discarded_ids
        return ToolPostprocessEffect(
            replacement_result=None if suppressed else tool_result(
                success=True,
                tool_chains_compressed=len(replacements),
                messages_removed=messages_removed,
                remaining=history.count,
            ),
            suppress_tool_result_event=suppressed,
            discarded_tool_call_ids=discarded_ids,
            system_message="Tool chain compression complete",
        )


TOOLSET = BaseToolSet(
    name="core",
    tools=(CompressToolChainsTool(),),
)
