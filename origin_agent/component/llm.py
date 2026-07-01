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
from typing import Any, Dict, Iterator, List, Optional

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
                    content=_extract_content(msg),
                    tool_calls=_extract_tool_calls(msg),
                    finish_reason=_extract_finish_reason(choice),
                    reasoning_content=_extract_reasoning(msg),
                    usage=_extract_usage(completion),
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
                        if not chunk.choices and getattr(chunk, "usage", None):
                            yield StreamChunk(usage=_extract_usage(chunk))
                            continue

                        choice = chunk.choices[0] if chunk.choices else None
                        if choice is None:
                            continue
                        delta = choice.delta
                        if delta is None:
                            continue

                        content_delta = _extract_content(delta)
                        reasoning_delta = _extract_reasoning(delta) or ""

                        if content_delta:
                            content_buffer += content_delta
                            yield StreamChunk(content_delta=content_delta)

                        if reasoning_delta:
                            reasoning_buffer += reasoning_delta
                            yield StreamChunk(reasoning_delta=reasoning_delta)

                        # 累积 tool_calls
                        for idx, tc_id, name_delta, args_delta in _iter_delta_tool_calls(delta):
                            if idx in completed_tool_indices:
                                continue
                            buf = tool_buffers.setdefault(idx, {
                                "id": "",
                                "name": "",
                                "arguments": "",
                            })
                            if tc_id:
                                buf["id"] = tc_id
                            if name_delta:
                                buf["name"] += name_delta
                            if args_delta:
                                buf["arguments"] += args_delta

                            # 当收集到 id、name 且 finish_reason 出现时认为完整
                            finish = _extract_finish_reason(choice)
                            if finish and buf["id"] and buf["name"]:
                                completed_tool_indices.add(idx)
                                yield StreamChunk(
                                    tool_call=ToolCall(
                                        id=buf["id"],
                                        name=buf["name"],
                                        arguments=_safe_json_parse(buf["arguments"]),
                                    )
                                )

                        finish = _extract_finish_reason(choice)
                        if finish:
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
                            yield StreamChunk(
                                finish_reason=finish,
                                usage=_extract_usage(chunk),
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


def _extract_content(obj: Any) -> str:
    """从 message/delta 对象中提取 assistant content。

    部分 provider 或 SDK 版本可能不暴露 ``content`` 字段，统一做防御式提取。
    """
    if obj is None:
        return ""
    return getattr(obj, "content", None) or ""


def _extract_reasoning(obj: Any) -> str | None:
    """从 OpenAI SDK 的 delta/message 对象中提取 reasoning 内容。

    不同 provider / SDK 版本对 reasoning 字段的命名和暴露方式不同：
      - DeepSeek: ``reasoning_content``
      - 某些 OpenAI 兼容接口: ``reasoning``
      - 标准 OpenAI ``ChoiceDelta``: 可能不存在该字段

    统一在此函数内做防御式提取，上层无需关心兼容细节，也便于
    后续升级为按 provider 配置的适配器模式。
    """
    if obj is None:
        return None
    for attr in ("reasoning_content", "reasoning"):
        value = getattr(obj, attr, None)
        if value:
            return value
    return None


def _extract_usage(obj: Any) -> Usage:
    """从 completion/chunk 对象中提取 token 消耗。

    某些 provider 在流式最终帧或特定错误场景下可能不返回 ``usage``，
    统一返回零值 ``Usage()`` 作为兜底。
    """
    if obj is None:
        return Usage()
    usage = getattr(obj, "usage", None)
    if usage is None:
        return Usage()
    return Usage(
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        total_tokens=getattr(usage, "total_tokens", 0) or 0,
    )


def _extract_finish_reason(choice: Any, default: str = "stop") -> str:
    """从 choice 对象中提取 finish_reason，缺失时返回默认值。"""
    if choice is None:
        return default
    return getattr(choice, "finish_reason", None) or default


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


def _parse_tool_call(tc: Any) -> ToolCall | None:
    """从完整的 tool_call 对象解析为 ToolCall。

    对字段缺失做防御式处理：``id``、``function.name`` 任一缺失时返回 ``None``。
    """
    if tc is None:
        return None
    tc_id = getattr(tc, "id", None)
    function = getattr(tc, "function", None)
    if not tc_id or not function:
        return None
    name = getattr(function, "name", None)
    if not name:
        return None
    arguments = getattr(function, "arguments", None) or ""
    return ToolCall(
        id=tc_id,
        name=name,
        arguments=_safe_json_parse(arguments),
    )


def _extract_tool_calls(obj: Any) -> list[ToolCall]:
    """从 message 对象中提取完整的 tool_calls 列表。"""
    if obj is None:
        return []
    tool_calls = getattr(obj, "tool_calls", None)
    if not tool_calls:
        return []
    result: list[ToolCall] = []
    for tc in tool_calls:
        parsed = _parse_tool_call(tc)
        if parsed:
            result.append(parsed)
    return result


def _iter_delta_tool_calls(
    delta: Any,
) -> Iterator[tuple[int, str | None, str | None, str | None]]:
    """从 ChoiceDelta 的 tool_calls 增量中安全提取片段。

    返回 ``(index, id, name_delta, arguments_delta)`` 元组。任意字段缺失时以
    ``None`` 占位，避免直接访问 ``tc.function.name`` 等可能不存在的属性。
    """
    if delta is None:
        return
    tool_calls = getattr(delta, "tool_calls", None)
    if not tool_calls:
        return
    for tc in tool_calls:
        idx = getattr(tc, "index", None)
        if idx is None:
            continue
        tc_id = getattr(tc, "id", None) or None
        function = getattr(tc, "function", None)
        name_delta = None
        arguments_delta = None
        if function is not None:
            name_delta = getattr(function, "name", None) or None
            arguments_delta = getattr(function, "arguments", None) or None
        yield idx, tc_id, name_delta, arguments_delta
