"""StreamConsumer — LLM 流式响应消费器。

封装 LLM 流式响应的增量消费、content/reasoning/tool_call 分发、
usage 统计、取消检查和迭代器安全关闭。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, TYPE_CHECKING

from abstract.llm.client import BaseLLMClient
from entity.puretype import LLMResponse, Usage, ToolCall
from entity.messages import BaseMessage

if TYPE_CHECKING:
    from entry.agent_sink import AgentSink

logger = logging.getLogger(__name__)


async def _close_async_iterator(ait: Any) -> None:
    """安全关闭异步迭代器，避免未读取完成的流留下资源泄漏。"""
    try:
        await ait.aclose()
    except Exception:
        logger.debug("Failed to close async iterator", exc_info=True)


class StreamConsumer:
    """消费一条 LLM 流式响应，边收边推送增量到前端。

    每个 LLM 调用创建一次 ``consume()``。
    接收独立依赖（llm / sink / character_name / cancel_event），本身不绑定任何 loop 类型。
    """

    def __init__(
        self,
        llm: BaseLLMClient,
        sink: AgentSink,
        character_name: str,
        cancel_event: asyncio.Event,
    ) -> None:
        self._llm = llm
        self._sink = sink
        self._character_name = character_name
        self._cancel_event = cancel_event

    async def consume(
        self,
        session_id: str,
        messages: list[BaseMessage],
        tools: list[dict[str, Any]] | None,
        stream_id: str,
    ) -> LLMResponse:
        """消费流式响应，返回聚合后的 LLMResponse。"""
        ev = self._cancel_event

        content: str = ""
        reasoning_content: str = ""
        reasoning_field_name: str | None = None
        tool_calls: list[ToolCall] = [] 
        finish_reason: str = "stop"
        usage_dict: dict[str, int] = {
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        }
        stream_error: str | None = None

        stream = self._llm.chat_stream(messages, tools=tools, character=self._character_name)
        try:
            async for chunk in stream:
                if ev.is_set():
                    break

                if chunk.error:
                    stream_error = chunk.error
                    break

                if chunk.content_delta:
                    content += chunk.content_delta
                    await self._sink.emit_stream_delta(
                        session_id, stream_id,
                        delta=chunk.content_delta,
                        character_name=self._character_name,
                    )

                if chunk.reasoning_delta:
                    reasoning_content += chunk.reasoning_delta
                    if chunk.reasoning_field_name:
                        reasoning_field_name = chunk.reasoning_field_name
                    await self._sink.emit_stream_delta(
                        session_id, stream_id,
                        reasoning_delta=chunk.reasoning_delta,
                        character_name=self._character_name,
                    )

                if chunk.tool_call:
                    tool_calls.append(chunk.tool_call)
                    await self._sink.emit_stream_delta(
                        session_id, stream_id,
                        tool_call={
                            "id": chunk.tool_call.id,
                            "name": chunk.tool_call.name,
                            "arguments": chunk.tool_call.arguments,
                        },
                        character_name=self._character_name,
                    )

                if chunk.usage:
                    usage_dict["prompt_tokens"] = chunk.usage.prompt_tokens
                    usage_dict["completion_tokens"] = chunk.usage.completion_tokens
                    usage_dict["total_tokens"] = chunk.usage.total_tokens

                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason
        finally:
            await _close_async_iterator(stream)

        if ev.is_set():
            finish_reason = "cancelled"

        if stream_error:
            raise RuntimeError(stream_error)

        if not ev.is_set() and usage_dict["total_tokens"] == 0:
            raise RuntimeError(
                "LLM provider did not return token usage for streaming response. "
                "Provider must support stream_options.include_usage."
            )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            reasoning_content=reasoning_content or None,
            reasoning_field_name=reasoning_field_name,
            usage=Usage(
                prompt_tokens=usage_dict["prompt_tokens"],
                completion_tokens=usage_dict["completion_tokens"],
                total_tokens=usage_dict["total_tokens"],
            ),
        )