"""OpenAI 兼容的 LLM 客户端。

提供两个接口：
  - ``chat()`` — 非流式请求，返回完整 :class:`LLMResponse`
  - ``chat_stream()`` — 流式请求，逐块 yield :class:`StreamChunk`

使用 ``openai`` SDK。配置来自 RuntimeContext
（api_key、base_url、model、temperature、max_tokens），
密钥通过环境变量兜底（``OPENAI_API_KEY``）。
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from typing import Any, Dict, List, Optional

import openai
from pydantic import BaseModel, ConfigDict

from system.context import RuntimeContext
from entity.constant import TOOL_RESULT_PREVIEW_CHARS, LLM_RETRY_COUNT, BACKOFF_BASE

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 响应类型
# ---------------------------------------------------------------------------


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    arguments: dict[str, Any] = {}


class Usage(BaseModel):
    """LLM 提供商返回的 token 消耗。"""
    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str = ""
    tool_calls: list[ToolCall] = []
    finish_reason: str = "stop"
    reasoning_content: str | None = None
    """DeepSeek thinking-mode 载荷 — 在后续回合中必须回传。"""
    usage: Usage = Usage()


class StreamChunk(BaseModel):
    """流式响应的一个片段。"""
    model_config = ConfigDict(frozen=True)

    content_delta: str | None = None
    reasoning_delta: str | None = None
    """DeepSeek thinking-mode 增量 — 仅用于展示。"""
    tool_call: ToolCall | None = None
    """当前 chunk 中首次完整出现的 tool_call（用于工具调用开始通知）。"""
    finish_reason: str | None = None
    usage: Usage | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------


class LLMClient:
    """OpenAI SDK 的薄封装。

    参数从 RuntimeContext 的 LLM 字段获取。
    ``api_key`` 兜底到 ``OPENAI_API_KEY`` 环境变量。
    """

    def __init__(self, ctx: RuntimeContext) -> None:
        api_key: str = ctx.llm_api_key or os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            logger.warning(
                "No LLM API key configured — set OPENAI_API_KEY env var "
                "or pass it via RuntimeContext"
            )

        self._client: openai.AsyncOpenAI = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=ctx.llm_base_url,
        )
        self._model: str = ctx.llm_model
        self._temperature: float = ctx.llm_temperature
        self._max_tokens: int = ctx.llm_max_output_tokens
        self._reasoning_effort: str = ctx.llm_reasoning_effort or ""

    # -- 公开 API ----------------------------------------------------------

    def _build_kwargs(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "max_completion_tokens": self._max_tokens,
            "stream": stream,
        }
        if stream:
            # 强制要求 provider 在流末尾返回 usage，否则无法统计上下文占用。
            kwargs["stream_options"] = {"include_usage": True}
        if tools:
            kwargs["tools"] = tools
        if self._reasoning_effort:
            kwargs["reasoning_effort"] = self._reasoning_effort
        return kwargs

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> LLMResponse:
        """发送聊天请求，返回结构化响应。

        对 transient 网络错误（连接中断、超时、限流、5xx）
        自动进行指数退避重试，最多 ``LLM_RETRY_COUNT`` 次。

        *messages* 为 OpenAI 格式的消息字典列表
        （``{"role": "...", "content": "..."}``）。
        *tools* 为可选的 OpenAI 格式工具 schema 列表。

        返回包含 assistant 内容和工具调用的 :class:`LLMResponse`。
        """
        kwargs = self._build_kwargs(messages, tools, stream=False)

        for attempt in range(LLM_RETRY_COUNT):
            try:
                completion: Any = await self._client.chat.completions.create(**kwargs)
                if not completion.choices:
                    raise RuntimeError("LLM returned empty choices list")
                choice: Any = completion.choices[0]
                msg: Any = choice.message

                return LLMResponse(
                    content=msg.content or "",
                    tool_calls=[
                        ToolCall(
                            id=tc.id,
                            name=tc.function.name,
                            arguments=_safe_json_parse(tc.function.arguments),
                        )
                        for tc in (msg.tool_calls or [])
                    ],
                    finish_reason=choice.finish_reason or "stop",
                    reasoning_content=msg.reasoning_content,
                    usage=Usage(
                        prompt_tokens=completion.usage.prompt_tokens if completion.usage else 0,
                        completion_tokens=completion.usage.completion_tokens if completion.usage else 0,
                        total_tokens=completion.usage.total_tokens if completion.usage else 0,
                    ),
                )
            except (
                openai.APIConnectionError,
                openai.APITimeoutError,
                openai.RateLimitError,
                openai.InternalServerError,
            ) as exc:
                if attempt < LLM_RETRY_COUNT - 1:
                    wait: float = BACKOFF_BASE * (2 ** attempt)
                    logger.warning(
                        "LLM transient error (attempt %d/%d): %s. Retrying in %.1fs...",
                        attempt + 1, LLM_RETRY_COUNT, exc, wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error("LLM transient error exhausted all %d retries: %s", LLM_RETRY_COUNT, exc)
                    raise exc
            except Exception:
                # 非 transient 异常（如认证失败、BadRequestError 等）立即抛出
                raise
        # 所有代码路径都已 return 或 raise，此处不可达（保留以安抚类型检查器）
        raise AssertionError("unreachable")

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> AsyncIterator[StreamChunk]:
        """发送流式聊天请求，逐块返回增量内容。

        支持 content、reasoning_content 的增量输出，以及 tool_calls 的
        完整累积输出。流结束时会发出一个带 ``finish_reason`` 的空 chunk。
        """
        kwargs = self._build_kwargs(messages, tools, stream=True)

        for attempt in range(LLM_RETRY_COUNT):
            try:
                async with await self._client.chat.completions.create(**kwargs) as stream:
                    content_buffer: str = ""
                    reasoning_buffer: str = ""
                    tool_buffers: dict[int, dict[str, Any]] = {}
                    completed_tool_indices: set[int] = set()

                    async for chunk in stream:
                        # include_usage 模式下，OpenAI 在最终发送一个
                        # choices 为空但携带 usage 的独立 chunk，需要单独提取
                        if not chunk.choices and chunk.usage:
                            yield StreamChunk(
                                usage=Usage(
                                    prompt_tokens=chunk.usage.prompt_tokens,
                                    completion_tokens=chunk.usage.completion_tokens,
                                    total_tokens=chunk.usage.total_tokens,
                                ),
                            )
                            continue

                        choice = chunk.choices[0] if chunk.choices else None
                        if choice is None:
                            continue
                        delta = choice.delta
                        if delta is None:
                            continue

                        content_delta = delta.content or ""
                        reasoning_delta = delta.reasoning_content or ""

                        if content_delta:
                            content_buffer += content_delta
                            yield StreamChunk(content_delta=content_delta)

                        if reasoning_delta:
                            reasoning_buffer += reasoning_delta
                            yield StreamChunk(reasoning_delta=reasoning_delta)

                        # 累积 tool_calls
                        for tc in (delta.tool_calls or []):
                            idx: int = tc.index
                            if idx in completed_tool_indices:
                                continue
                            buf = tool_buffers.setdefault(idx, {
                                "id": "",
                                "name": "",
                                "arguments": "",
                            })
                            if tc.id:
                                buf["id"] = tc.id
                            if tc.function:
                                if tc.function.name:
                                    buf["name"] += tc.function.name
                                if tc.function.arguments:
                                    buf["arguments"] += tc.function.arguments

                            # 当收集到 id、name 且 finish_reason 出现时认为完整
                            finish = choice.finish_reason
                            if finish and buf["id"] and buf["name"]:
                                completed_tool_indices.add(idx)
                                yield StreamChunk(
                                    tool_call=ToolCall(
                                        id=buf["id"],
                                        name=buf["name"],
                                        arguments=_safe_json_parse(buf["arguments"]),
                                    )
                                )

                        if choice.finish_reason:
                            # 某些 provider 在 finish_reason 时仍未触发 tool_call 完成，兜底
                            for idx, buf in tool_buffers.items():
                                if idx in completed_tool_indices:
                                    continue
                                if buf["id"] and buf["name"]:
                                    completed_tool_indices.add(idx)
                                    yield StreamChunk(
                                        tool_call=ToolCall(
                                            id=buf["id"],
                                            name=buf["name"],
                                            arguments=_safe_json_parse(buf["arguments"]),
                                        )
                                    )
                            usage = Usage(
                                prompt_tokens=chunk.usage.prompt_tokens if chunk.usage else 0,
                                completion_tokens=chunk.usage.completion_tokens if chunk.usage else 0,
                                total_tokens=chunk.usage.total_tokens if chunk.usage else 0,
                            )
                            yield StreamChunk(
                                finish_reason=choice.finish_reason,
                                usage=usage,
                            )

                return
            except (
                openai.APIConnectionError,
                openai.APITimeoutError,
                openai.RateLimitError,
                openai.InternalServerError,
            ) as exc:
                if attempt < LLM_RETRY_COUNT - 1:
                    wait: float = BACKOFF_BASE * (2 ** attempt)
                    logger.warning(
                        "LLM stream transient error (attempt %d/%d): %s. Retrying in %.1fs...",
                        attempt + 1, LLM_RETRY_COUNT, exc, wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error("LLM stream transient error exhausted all %d retries: %s", LLM_RETRY_COUNT, exc)
                    yield StreamChunk(error=f"{exc}")
                    return
            except openai.APIStatusError as exc:
                # 非 transient 的 HTTP 状态错误（如 400、401）立即报告
                logger.error("LLM stream API status error: %s", exc)
                yield StreamChunk(error=f"{exc}")
                return
            except Exception as exc:
                logger.exception("LLM stream unexpected error")
                yield StreamChunk(error=f"{exc}")
                return


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------


def _safe_json_parse(raw: str) -> dict[str, Any]:
    import dirtyjson

    try:
        result = dirtyjson.loads(raw)
        if isinstance(result, dict):
            return result
    except Exception as exc:
        logger.warning(
            "Failed to parse tool call arguments (%d chars): %s: %s",
            len(raw), type(exc).__name__, exc,
        )
        return {
            "_parse_error": True,
            "_parse_error_type": type(exc).__name__,
            "_parse_error_msg": str(exc),
            "_raw_preview": raw[:TOOL_RESULT_PREVIEW_CHARS],
        }

    logger.warning(
        "Failed to parse tool call arguments (%d chars): %s …",
        len(raw), raw[:300],
    )
    return {"_parse_error": True, "_raw_preview": raw[:TOOL_RESULT_PREVIEW_CHARS]}
