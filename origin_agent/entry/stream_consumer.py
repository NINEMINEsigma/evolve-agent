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
from entity.constant import LLM_STREAM_IDLE_TIMEOUT

if TYPE_CHECKING:
    from entry.agent_sink import AgentSink

logger = logging.getLogger(__name__)


async def _close_async_iterator(ait: Any) -> None:
    """安全关闭异步迭代器，避免未读取完成的流留下资源泄漏。

    对已断开/无响应的连接限时 2 秒，防止关闭本身挂起阻塞中断收尾。
    """
    try:
        await asyncio.wait_for(ait.aclose(), timeout=2.0)
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
        # 当前活动流的底层异步迭代器与最后一次部分结果快照；由主会话层
        # 在取消时调用 cancel_stream() 解除网络阻塞，partial_result() 取回已显示内容。
        self._active_iterator: Any | None = None
        self._last_partial: LLMResponse | None = None

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
        self._active_iterator = stream
        idle_timeout = LLM_STREAM_IDLE_TIMEOUT
        next_task: asyncio.Task | None = None
        cancel_waiter: asyncio.Task | None = None
        try:
            while True:
                # 三路竞速：下一块流数据 / 用户取消事件 / 空闲超时。
                # 取消事件一旦置位立即退出，不依赖 task.cancel() 打断阻塞的网络读取；
                # 超时与用户取消不共享 CancelledError 边界。
                next_task = asyncio.ensure_future(stream.__anext__())
                cancel_waiter = asyncio.ensure_future(ev.wait())
                done, _pending = await asyncio.wait(
                    {next_task, cancel_waiter},
                    timeout=idle_timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    # 连续 idle_timeout 秒无任何流式数据：自动停止本轮
                    next_task.cancel()
                    cancel_waiter.cancel()
                    for t in (next_task, cancel_waiter):
                        try:
                            await t
                        except (asyncio.CancelledError, Exception):
                            pass
                    stream_error = (
                        f"LLM stream idle timeout: no data received for "
                        f"{idle_timeout}s"
                    )
                    break

                if cancel_waiter in done:
                    # 用户取消：丢弃未完成的读取，直接结束（finish_reason=cancelled）
                    next_task.cancel()
                    try:
                        await next_task
                    except (asyncio.CancelledError, Exception):
                        pass
                    break
                cancel_waiter.cancel()
                try:
                    await cancel_waiter
                except (asyncio.CancelledError, Exception):
                    pass

                try:
                    chunk = next_task.result()
                except StopAsyncIteration:
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
            self._active_iterator = None

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

        response = LLMResponse(
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
        # 保存本轮快照供取消路径取回（不含未完成的 tool_call 参数）
        self._last_partial = response
        return response

    def partial_result(self, *, finish_reason: str = "cancelled") -> LLMResponse | None:
        """返回当前已显示内容的快照（完整 tool_calls 之前的部分）。

        用于强制中断时保留用户已看到的部分文字；不伪造未完成的工具调用。
        无已收到内容时返回 None。
        """
        snapshot = self._last_partial
        if snapshot is None:
            return None
        return snapshot.model_copy(update={"finish_reason": finish_reason})

    async def cancel_stream(self) -> None:
        """主动关闭当前活动流，解除 chat_stream 的网络阻塞。

        由主会话层在强制中断时调用；关闭后当前 ``consume()`` 的下一轮
        ``__anext__`` 会抛错或结束，由 Loop 取消边界负责收尾。
        """
        it = self._active_iterator
        if it is not None:
            await _close_async_iterator(it)