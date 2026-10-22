"""工具链压缩共享逻辑：准备替换材料与收集待删除调用，均不修改 History。

``prepare_tool_chain_replacements`` 在调用方取得历史快照后准备全部替换材料；
``collect_tool_call_ids`` 收集被替换/截断区间内的真实工具调用 ID，供前端移除
已消失的实时工具卡片。两者都不触碰 History，也不访问运行时服务。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from entity.messages import BaseMessage, CharacterConversationMessage
from entity.puretype_after import ToolChainReplacement
from entry.agent_support.tool_chain_compress import (
    build_compressed_chain_messages,
    chain_to_summary_input,
    detect_compressible_chains,
)

if TYPE_CHECKING:
    from interface.session_metadata_service import ISessionMetadataService


async def prepare_tool_chain_replacements(
    messages: list[BaseMessage],
    *,
    session_id: str,
    metadata_service: ISessionMetadataService,
    start_index: int = 0,
    excluded_tool_call_ids: set[str] | None = None
    ) -> list[ToolChainReplacement]:
    """从 start_index 起准备全部替换材料；失败与取消直接传播。

    ``excluded_tool_call_ids`` 中的任一 ID 命中一条链时整条链跳过：当前调用
    所在链因此保持原样（例如 CompressHistory 保护本轮），而传入空集合时
    全历史扫描包含本次调用自身（CompressToolChains）。
    """
    replacements: list[ToolChainReplacement] = []
    for span in detect_compressible_chains(
        messages[start_index:],
        excluded_tool_call_ids=excluded_tool_call_ids,
    ):
        start = start_index + span.start
        end = start_index + span.end
        chain_messages = messages[start:end]
        summary = await metadata_service.generate_tool_chain_summary(
            session_id, chain_to_summary_input(chain_messages),
        )
        replacements.append(
            ToolChainReplacement(
                start=start,
                end=end,
                messages=build_compressed_chain_messages(chain_messages, summary),
            )
        )
    return replacements


def collect_tool_call_ids(
    messages: list[BaseMessage],
    ranges: list[tuple[int, int]],
) -> tuple[str, ...]:
    """收集给定半开区间 [start, end) 内 assistant 消息携带的全部 tool_call_id。

    压缩 after 用它告诉前端哪些实时工具卡片因链被替换或轮次被截断而消失。
    区间按构造互不重叠，仅按历史顺序拼接。
    """
    collected: list[str] = []
    for start, end in ranges:
        for message in messages[start:end]:
            if isinstance(message, CharacterConversationMessage) and message.tool_calls:
                collected.extend(call.id for call in message.tool_calls)
    return tuple(collected)
