"""工具链压缩 — 将完整工具链重打包为一次伪造工具调用及其摘要结果。

概念：
- 工具链：历史中一段连续消息，仅由「带 tool_calls 的 assistant 消息」和
  ``ToolResultMessage`` 组成；遇到 user / 纯文本 assistant / system 消息即结束。
- 可压缩链：链内每个 tool_call 都已有配对的 ToolResultMessage（进行中的
  当前轮调用天然无结果，因此当前轮链被排除），且原始文本体积达到阈值。
- 重打包：整链替换为恰好两条消息——带伪造 tool_call（不可调用的
  ``COMPRESSED_TOOL_CHAIN_CALL_NAME``）的 assistant 消息，以及携带链摘要的
  配对 ToolResultMessage，配对约束由构造保证。

本模块只做纯函数式检测与构造，不访问运行时服务；摘要生成由调用方
（CompressHistory 工具）经 SessionMetadataService 完成。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from entity.constant import (
    COMPRESSED_TOOL_CHAIN_CALL_NAME,
    TOOL_CHAIN_COMPRESS_MIN_CHARS,
)
from entity.messages import (
    BaseMessage,
    CharacterConversationMessage,
    FunctionCall,
    ToolCall,
    ToolResultMessage,
)
from entity.puretype import Role, ToolChainSpan
from entry.agent_support.history_summary import messages_to_text


def _is_chain_member(message: BaseMessage) -> bool:
    """返回消息是否属于工具链成员（assistant 工具调用或工具结果）。"""
    if isinstance(message, ToolResultMessage):
        return True
    return _is_chain_start(message)


def _is_chain_start(message: BaseMessage) -> bool:
    """返回消息是否可以作为工具链起点（带 tool_calls 的 assistant 消息）。"""
    return (
        isinstance(message, CharacterConversationMessage)
        and message.role == Role.ASSISTANT
        and bool(message.tool_calls)
    )


def _message_size(message: BaseMessage) -> int:
    """估算单条消息的原始文本体积（字符），含 tool_calls 参数。"""
    content: Any = message.content
    if content is None:
        size = 0
    elif isinstance(content, str):
        size = len(content)
    elif isinstance(content, dict):
        size = len(json.dumps(content, ensure_ascii=False))
    else:
        size = sum(len(block.model_dump_json()) for block in content)
    if isinstance(message, CharacterConversationMessage) and message.tool_calls:
        size += sum(len(tc.function.arguments) for tc in message.tool_calls)
    return size


def detect_compressible_chains(
    messages: list[BaseMessage],
    min_chars: int = TOOL_CHAIN_COMPRESS_MIN_CHARS,
) -> list[ToolChainSpan]:
    """检测消息列表中所有可压缩工具链，返回半开区间列表。

    可压缩条件：
    1. 链内每个 tool_call 的 id 都能在整条历史中找到配对 ToolResultMessage
       （进行中的调用没有结果，其所在链整体被排除）；
    2. 链的原始文本体积不低于 ``min_chars``。
    """
    result_ids: set[str] = {
        msg.tool_call_id for msg in messages if isinstance(msg, ToolResultMessage)
    }
    spans: list[ToolChainSpan] = []
    index = 0
    total = len(messages)
    while index < total:
        if not _is_chain_start(messages[index]):
            index += 1
            continue
        start = index
        call_ids: list[str] = []
        size = 0
        while index < total and _is_chain_member(messages[index]):
            current = messages[index]
            if isinstance(current, CharacterConversationMessage) and current.tool_calls:
                call_ids.extend(tc.id for tc in current.tool_calls)
            size += _message_size(current)
            index += 1
        if (
            all(call_id in result_ids for call_id in call_ids)
            and size >= min_chars
        ):
            spans.append(ToolChainSpan(start=start, end=index))
    return spans


def chain_to_summary_input(chain_messages: list[BaseMessage]) -> str:
    """把一条工具链转换为摘要模型输入文本。

    不做全局截断：``messages_to_text`` 已对每条工具结果应用预览上限，
    长链的完整信息量应保留给摘要模型。
    """
    return messages_to_text(chain_messages)


def build_compressed_chain_messages(
    chain_messages: list[BaseMessage],
    summary: str,
) -> list[BaseMessage]:
    """把一条工具链重打包为 [伪造 assistant 调用消息, 摘要结果消息]。

    伪造 tool_call 使用不可调用的 ``COMPRESSED_TOOL_CHAIN_CALL_NAME``，
    参数携带链的紧凑元信息；摘要写入配对的 ToolResultMessage。
    """
    first = chain_messages[0]
    if not isinstance(first, CharacterConversationMessage):
        raise TypeError("tool chain must start with an assistant tool call message")

    tool_names: list[str] = []
    call_count = 0
    for message in chain_messages:
        if isinstance(message, CharacterConversationMessage) and message.tool_calls:
            for tool_call in message.tool_calls:
                tool_names.append(tool_call.function.name)
                call_count += 1

    call_id = f"compressed_chain_{uuid.uuid4().hex}"
    arguments = json.dumps(
        {"tool_calls": call_count, "tools": tool_names},
        ensure_ascii=False,
    )
    assistant_message = CharacterConversationMessage(
        role=Role.ASSISTANT,
        character_name=first.character_name,
        content=f"[Compressed tool chain: {call_count} call(s)]",
        visible_characters=first.visible_characters,
        tool_calls=[
            ToolCall(
                id=call_id,
                type="function",
                function=FunctionCall(
                    name=COMPRESSED_TOOL_CHAIN_CALL_NAME,
                    arguments=arguments,
                ),
            )
        ],
    )
    result_message = ToolResultMessage(
        role=Role.TOOL,
        character_name=first.character_name,
        tool_call_id=call_id,
        content={
            "compressed_tool_chain": True,
            "tool_calls": call_count,
            "tools": tool_names,
            "summary": summary,
        },
    )
    return [assistant_message, result_message]
