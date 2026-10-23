"""在正式客户端入口统一重试正常结束的 LLM 空响应。

本层只重试无正文且无工具输出的结果，不捕获 Provider 异常，不重放工具轮。
流式调用保留实时增量，但只有确认结果有效后才向上层交付结束原因。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing
from typing import Any, cast

from abstract.llm.client import BaseLLMClient, LLMEmptyResponseError
from entity.constant import BACKOFF_BASE, LLM_EMPTY_RESPONSE_MAX_ATTEMPTS
from entity.messages import BaseMessage, CharacterConversationMessage
from entity.puretype import LLMResponse, StreamChunk, Usage

logger = logging.getLogger(__name__)


async def _wait_before_empty_retry(
    attempt: int,
    *,
    character: str,
    streaming: bool
    ) -> None:
    """对明确的空响应执行有界退避；attempt 为已失败尝试的零基索引。"""
    if attempt + 1 == LLM_EMPTY_RESPONSE_MAX_ATTEMPTS:
        logger.error(
            "LLM empty response attempts exhausted | character=%s streaming=%s attempts=%d",
            character, streaming, LLM_EMPTY_RESPONSE_MAX_ATTEMPTS,
        )
        raise LLMEmptyResponseError(
            f"LLM returned empty content and no tool calls after "
            f"{LLM_EMPTY_RESPONSE_MAX_ATTEMPTS} attempts."
        )

    wait = BACKOFF_BASE * (2 ** attempt)
    logger.warning(
        "LLM returned empty content and no tool calls | "
        "character=%s streaming=%s attempt=%d/%d retry_in=%.1fs",
        character, streaming, attempt + 1, LLM_EMPTY_RESPONSE_MAX_ATTEMPTS, wait,
    )
    await asyncio.sleep(wait)


class EmptyResponseRetryClient(BaseLLMClient):
    """装饰一个 Provider 客户端，所有尝试状态均归属于单次调用。"""

    def __init__(self, client: BaseLLMClient) -> None:
        self._client = client

    async def chat(
        self,
        messages: list[BaseMessage],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, str] | None = None,
        character: str = "",
        *,
        last_user_message: CharacterConversationMessage | None = None,
        require_tool_call: bool = False
        ) -> LLMResponse:
        """只对正常返回的空结果重试，其他结果和异常保持原语义。"""
        for attempt in range(LLM_EMPTY_RESPONSE_MAX_ATTEMPTS):
            response = await self._client.chat(
                messages,
                tools=tools,
                response_format=response_format,
                character=character,
                last_user_message=last_user_message,
                require_tool_call=require_tool_call,
            )
            if response.content or response.tool_calls:
                return response
            await _wait_before_empty_retry(
                attempt, character=character, streaming=False,
            )
        raise AssertionError("unreachable")

    async def chat_stream(
        self,
        messages: list[BaseMessage],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, str] | None = None,
        character: str = "",
        *,
        last_user_message: CharacterConversationMessage | None = None,
        require_tool_call: bool = False
        ) -> AsyncIterator[StreamChunk]:
        """透传实时输出，在自然结束且没有正文/工具时重新请求原始输入。

        推理增量在同一逻辑流中连续保留；失败尝试不追加到请求消息。
        usage 在出现正文或完整工具之前暂存，避免空尝试污染后续用量。
        """
        for attempt in range(LLM_EMPTY_RESPONSE_MAX_ATTEMPTS):
            has_content = False
            has_tool_call = False
            has_tool_delta = False
            finish_reason: str | None = None
            pending_usage: list[Usage] = []

            # BaseLLMClient 的流式契约要求 aclose；cast 只补充该静态类型约定。
            stream = cast(
                AsyncGenerator[StreamChunk, None],
                self._client.chat_stream(
                    messages,
                    tools=tools,
                    response_format=response_format,
                    character=character,
                    last_user_message=last_user_message,
                    require_tool_call=require_tool_call,
                ),
            )
            async with aclosing(stream):
                async for chunk in stream:
                    if chunk.error:
                        yield chunk
                        return

                    if chunk.content_delta:
                        has_content = True
                    if chunk.tool_call is not None:
                        has_tool_call = True
                    if chunk.tool_call_delta is not None:
                        has_tool_delta = True
                    if chunk.finish_reason:
                        finish_reason = chunk.finish_reason

                    usage = chunk.usage
                    if has_content or has_tool_call:
                        for buffered_usage in pending_usage:
                            yield StreamChunk(usage=buffered_usage)
                        pending_usage.clear()
                    elif usage is not None:
                        pending_usage.append(usage)
                        usage = None

                    # 即使只剩空 chunk 也保留本次真实读取进展，避免改变空闲超时。
                    # 所有终态都等底层自然结束并完成关闭后才交付。
                    yield chunk.model_copy(update={
                        "finish_reason": None,
                        "usage": usage,
                    })

            if has_content or has_tool_call:
                if finish_reason is not None:
                    yield StreamChunk(finish_reason=finish_reason)
                return

            if has_tool_delta:
                # 已显示的工具参数片段不重播，也不能伪装成合法的空工具列表。
                raise LLMEmptyResponseError(
                    "LLM returned incomplete tool call deltas without content "
                    "or a complete tool call; the response will not be retried."
                )

            await _wait_before_empty_retry(
                attempt, character=character, streaming=True,
            )
        raise AssertionError("unreachable")
