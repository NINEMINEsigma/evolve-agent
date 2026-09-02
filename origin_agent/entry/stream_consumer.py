"""StreamConsumer — LLM 流 → 前端的唯一桥接层。

封装 LLM 流式响应的增量消费、content/reasoning/tool_call/tool_call_delta
分发、usage 绂计、取消检查和迭代器安全关闭。

主 loop 与 multi-agent worker 均经由此处转发流式增量到前端，
确保"流式 → 前端"路径统一为一条。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, TYPE_CHECKING

from abstract.llm.client import BaseLLMClient
from entity.puretype import LLMResponse, Usage, ToolCallRequest, MessageMetrics
from entity.messages import BaseMessage, CharacterConversationMessage

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
        llm: BaseLLMClient | None,
        sink: AgentSink,
        character_name: str,
        cancel_event: asyncio.Event,
    ) -> None:
        self._llm = llm
        self._sink = sink
        self._character_name = character_name
        self._cancel_event = cancel_event

    @property
    def llm(self) -> BaseLLMClient | None:
        return self._llm

    @llm.setter
    def llm(self, value: BaseLLMClient | None) -> None:
        self._llm = value

    async def consume(
        self,
        session_id: str,
        messages: list[BaseMessage],
        tools: list[dict[str, Any]] | None,
        stream_id: str,
        *,
        last_user_message: CharacterConversationMessage | None = None,
    ) -> LLMResponse:
        """消费流式响应，返回聚合后的 LLMResponse。"""
        llm = self._llm
        if llm is None:
            raise RuntimeError("No LLM client available for stream consumption")
        ev = self._cancel_event

        content: str = ""
        reasoning_content: str = ""
        reasoning_field_name: str | None = None
        tool_calls: list[ToolCallRequest] = []
        finish_reason: str = "stop"
        usage_dict: dict[str, int] = {
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        }
        stream_error: str | None = None

        # 计时变量 — 基于 time.monotonic() 增量到达时间记录
        reasoning_start_ts: float | None = None
        reasoning_end_ts: float | None = None
        content_start_ts: float | None = None
        content_end_ts: float | None = None

        stream = llm.chat_stream(
            messages, tools=tools, character=self._character_name,
            last_user_message=last_user_message,
        )
        try:
            async for chunk in stream:
                if ev.is_set():
                    break

                if chunk.error:
                    stream_error = chunk.error
                    break

                if chunk.content_delta:
                    if content_start_ts is None:
                        content_start_ts = time.monotonic()
                    content_end_ts = time.monotonic()
                    content += chunk.content_delta
                    await self._sink.emit_stream_delta(
                        session_id, stream_id,
                        delta=chunk.content_delta,
                        character_name=self._character_name,
                    )

                if chunk.reasoning_delta:
                    if reasoning_start_ts is None:
                        reasoning_start_ts = time.monotonic()
                    reasoning_end_ts = time.monotonic()
                    reasoning_content += chunk.reasoning_delta
                    if chunk.reasoning_field_name:
                        reasoning_field_name = chunk.reasoning_field_name
                    await self._sink.emit_stream_delta(
                        session_id, stream_id,
                        reasoning_delta=chunk.reasoning_delta,
                        character_name=self._character_name,
                    )

                if chunk.tool_call_delta:
                    await self._sink.emit_stream_delta(
                        session_id, stream_id,
                        tool_call_delta=chunk.tool_call_delta.model_dump(exclude_none=True),
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
            logger.warning(
                "LLM provider did not return token usage for streaming response.",
            )
            # NOTE: 借用404代指无效的total_tokens
            usage_dict["total_tokens"] = 404

        # 计算计时数据
        reasoning_duration_ms = 0
        if reasoning_start_ts is not None and reasoning_end_ts is not None:
            reasoning_duration_ms = int((reasoning_end_ts - reasoning_start_ts) * 1000)

        content_duration_ms = 0
        if content_start_ts is not None and content_end_ts is not None:
            content_duration_ms = int((content_end_ts - content_start_ts) * 1000)

        total_duration_ms = reasoning_duration_ms + content_duration_ms
        completion_tokens = usage_dict["completion_tokens"]
        tokens_per_second = 0.0
        if total_duration_ms > 0 and completion_tokens > 0:
            tokens_per_second = round(completion_tokens / (total_duration_ms / 1000), 2)

        metrics = MessageMetrics(
            reasoning_duration_ms=reasoning_duration_ms,
            content_duration_ms=content_duration_ms,
            completion_tokens=completion_tokens,
            tokens_per_second=tokens_per_second,
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
            metrics=metrics,
        )