"""Anthropic 兼容的 LLM 客户端。

提供两个接口：
  - ``chat()`` — 非流式请求，返回完整 :class:`LLMResponse`
  - ``chat_stream()`` — 流式请求，逐块 yield :class:`StreamChunk`

使用 ``anthropic`` SDK。配置来自 RuntimeContext
（api_key、base_url、model、temperature、max_output_tokens），
密钥通过环境变量兜底（``ANTHROPIC_API_KEY``）。

支持 thinking（reasoning）内容的解析与续传。
``response_format`` 在本实现中忽略。
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from typing import Any, Optional

import anthropic
import dirtyjson
import httpcore
import httpx
import json

from abstract.llm.client import BaseLLMClient
from abstract.llm.formats import messages_to_anthropic_list
from entity.messages import BaseMessage
from entity.puretype import LLMResponse, StreamChunk, ToolCall, Usage
from entity.constant import (
    BACKOFF_BASE,
    LLM_RETRY_COUNT,
    TOOL_RESULT_PREVIEW_CHARS,
)
from system.context import RuntimeContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------


class AnthropicLLMClient(BaseLLMClient):
    """Anthropic SDK 的薄封装。

    接收 ``api_key``、``base_url``、``model``、``temperature``、
    ``max_output_tokens`` 等具体参数。
    ``api_key`` 兜底到 ``ANTHROPIC_API_KEY`` 环境变量。

    如需从 ``RuntimeContext`` 构造，使用 :meth:`from_context`。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float,
        max_output_tokens: int,
    ) -> None:
        if not api_key:
            logger.warning(
                "No Anthropic API key configured — set ANTHROPIC_API_KEY env var "
                "or pass it via constructor"
            )

        self._client: anthropic.AsyncAnthropic = anthropic.AsyncAnthropic(
            api_key=api_key,
            base_url=base_url,
        )
        self._model: str = model
        self._temperature: float = temperature
        self._max_tokens: int = max_output_tokens

    @classmethod
    def from_context(cls, ctx: RuntimeContext) -> AnthropicLLMClient:
        """从 RuntimeContext 构造 Anthropic LLM 客户端。"""
        return cls(
            api_key=ctx.llm_api_key or os.environ.get("ANTHROPIC_API_KEY", ""),
            base_url=ctx.llm_base_url,
            model=ctx.llm_model,
            temperature=ctx.llm_temperature,
            max_output_tokens=ctx.llm_max_output_tokens,
        )

    # -- 内部构造请求参数 --------------------------------------------------

    def _build_kwargs(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: Optional[list[dict[str, Any]]] = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        """构造 Anthropic Messages API 的请求参数。"""
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "messages": messages,
            "stream": stream,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools
        return kwargs

    # -- 公开 API ----------------------------------------------------------

    async def chat(
        self,
        messages: list[BaseMessage],
        tools: Optional[list[dict[str, Any]]] = None,
        response_format: Optional[dict[str, str]] = None,
        character: str = "",
    ) -> LLMResponse:
        """发送聊天请求，返回结构化响应。

        对 transient 网络错误（连接中断、超时、限流、5xx）
        自动进行指数退避重试，最多 ``LLM_RETRY_COUNT`` 次。
        """
        anthropic_messages, system = messages_to_anthropic_list(
            messages, current_character_agent=character
        )
        anthropic_tools = _openai_tools_to_anthropic(tools) if tools else None
        kwargs = self._build_kwargs(
            anthropic_messages, system, anthropic_tools, stream=False
        )

        for attempt in range(LLM_RETRY_COUNT):
            try:
                response: Any = await self._client.messages.create(**kwargs)
                return _parse_message(response)
            except (
                anthropic.APIConnectionError,
                anthropic.APITimeoutError,
                anthropic.RateLimitError,
                anthropic.InternalServerError,
            ) as exc:
                if attempt < LLM_RETRY_COUNT - 1:
                    wait: float = BACKOFF_BASE * (2 ** attempt)
                    logger.warning(
                        "Anthropic transient error (attempt %d/%d): %s. Retrying in %.1fs...",
                        attempt + 1,
                        LLM_RETRY_COUNT,
                        exc,
                        wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(
                        "Anthropic transient error exhausted all %d retries: %s",
                        LLM_RETRY_COUNT,
                        exc,
                    )
                    raise
            except Exception:
                # 非 transient 异常（如认证失败、BadRequestError 等）立即抛出
                raise

        # 所有代码路径都已 return 或 raise，此处不可达（保留以安抚类型检查器）
        raise AssertionError("unreachable")

    async def chat_stream(
        self,
        messages: list[BaseMessage],
        tools: Optional[list[dict[str, Any]]] = None,
        response_format: Optional[dict[str, str]] = None,
        character: str = "",
    ) -> AsyncIterator[StreamChunk]:
        """发送流式聊天请求，逐块返回增量内容。

        支持 content 增量、reasoning 增量、tool_use 的完整输出，并在流结束时发出带
        ``finish_reason`` 的 chunk。流中断时支持断点续传。
        """
        anthropic_messages, system = messages_to_anthropic_list(
            messages, current_character_agent=character
        )
        original_messages: list[dict[str, Any]] = list(anthropic_messages)
        anthropic_tools = _openai_tools_to_anthropic(tools) if tools else None
        state: dict[str, Any] = {
            "content": "",
            "reasoning": "",
            "reasoning_field_name": "reasoning_content",
            "completed_tool_calls": [],
            "finish_reason": None,
        }

        for attempt in range(LLM_RETRY_COUNT):
            resume_messages = (
                original_messages
                if attempt == 0
                else _build_resume_messages(original_messages, state)
            )
            try:
                kwargs = self._build_kwargs(
                    resume_messages, system, anthropic_tools, stream=True
                )
                stream = await self._client.messages.create(**kwargs)
                async with stream:
                    async for chunk in self._consume_one_stream(stream, state):
                        yield chunk
                return
            except _StreamInterruptedError:
                logger.warning(
                    "Anthropic stream interrupted (attempt %d/%d), resuming from breakpoint...",
                    attempt + 1,
                    LLM_RETRY_COUNT,
                )
                if attempt < LLM_RETRY_COUNT - 1:
                    wait: float = BACKOFF_BASE * (2 ** attempt)
                    await asyncio.sleep(wait)
                else:
                    logger.error("Anthropic stream resume attempts exhausted")
                    yield StreamChunk(
                        error="Anthropic stream interrupted and resume attempts exhausted."
                    )
                    return
            except (
                anthropic.APIConnectionError,
                anthropic.APITimeoutError,
                anthropic.RateLimitError,
                anthropic.InternalServerError,
            ) as exc:
                if attempt < LLM_RETRY_COUNT - 1:
                    wait = BACKOFF_BASE * (2 ** attempt)
                    logger.warning(
                        "Anthropic stream transient error (attempt %d/%d): %s. Retrying in %.1fs...",
                        attempt + 1,
                        LLM_RETRY_COUNT,
                        exc,
                        wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(
                        "Anthropic stream transient error exhausted all %d retries: %s",
                        LLM_RETRY_COUNT,
                        exc,
                    )
                    yield StreamChunk(error=f"{exc}")
                    return
            except anthropic.APIStatusError as exc:
                logger.error("Anthropic stream API status error: %s", exc)
                yield StreamChunk(error=f"{exc}")
                return
            except Exception as exc:
                logger.exception("Anthropic stream unexpected error")
                yield StreamChunk(error=f"{exc}")
                return

    async def _consume_one_stream(
        self,
        stream: Any,
        state: dict[str, Any],
    ) -> AsyncIterator[StreamChunk]:
        """消费单条 Anthropic 流，产出增量并返回结束状态。

        Anthropic 流事件类型：message_start / content_block_start /
        content_block_delta / content_block_stop / message_delta / message_stop。
        """
        current_tool_use: dict[str, Any] | None = None
        pending_tool_input: str = ""
        current_thinking: bool = False
        reasoning_buffer: str = state.get("reasoning", "")
        finish_reason: str | None = None
        pending_usage: Usage | None = None

        try:
            async for event in stream:
                event_type = getattr(event, "type", None)
                if event_type is None:
                    continue

                if event_type == "message_start":
                    message = getattr(event, "message", None)
                    if message is not None:
                        usage = _extract_usage(message)
                        if usage.total_tokens > 0:
                            yield StreamChunk(usage=usage)

                elif event_type == "content_block_start":
                    block = getattr(event, "content_block", None)
                    if block is not None:
                        block_type = getattr(block, "type", None)
                        if block_type == "thinking":
                            current_thinking = True
                        elif block_type == "tool_use":
                            current_tool_use = {
                                "id": getattr(block, "id", ""),
                                "name": getattr(block, "name", ""),
                            }
                            pending_tool_input = ""

                elif event_type == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    if delta is None:
                        continue
                    delta_type = getattr(delta, "type", None)
                    if delta_type == "text_delta":
                        text = getattr(delta, "text", "")
                        if text:
                            state["content"] = state.get("content", "") + text
                            yield StreamChunk(content_delta=text)
                    elif delta_type == "thinking_delta":
                        thinking_text = getattr(delta, "thinking", "")
                        if thinking_text:
                            reasoning_buffer += thinking_text
                            state["reasoning"] = reasoning_buffer
                            yield StreamChunk(
                                reasoning_delta=thinking_text,
                                reasoning_field_name="reasoning_content",
                            )
                    elif delta_type == "tool_use_delta":
                        partial = getattr(delta, "partial_json", "") or ""
                        pending_tool_input += partial

                elif event_type == "content_block_stop":
                    if current_thinking:
                        current_thinking = False
                    elif current_tool_use is not None:
                        block = getattr(event, "content_block", None)
                        final_input = getattr(block, "input", None)
                        if final_input is not None and isinstance(final_input, dict):
                            arguments = final_input
                        else:
                            arguments = _safe_json_parse(pending_tool_input)
                        tc = ToolCall(
                            id=current_tool_use["id"],
                            name=current_tool_use["name"],
                            arguments=arguments,
                        )
                        state["completed_tool_calls"].append(tc)
                        yield StreamChunk(tool_call=tc)
                        current_tool_use = None
                        pending_tool_input = ""

                elif event_type == "message_delta":
                    delta = getattr(event, "delta", None)
                    if delta is not None:
                        stop = getattr(delta, "stop_reason", None)
                        if stop:
                            finish_reason = _map_stop_reason(stop)
                    usage = _extract_usage(event)
                    if usage.total_tokens > 0:
                        pending_usage = usage

                elif event_type == "message_stop":
                    # 流正常结束，finish_reason 已在 message_delta 中记录
                    pass

        except Exception as exc:
            if _is_retriable_stream_error(exc):
                # 固化已完成的 tool_calls（包括未收到 content_block_stop 的当前 tool_use）
                if current_tool_use is not None and current_tool_use.get("id") and current_tool_use.get("name"):
                    arguments = _safe_json_parse(pending_tool_input)
                    state["completed_tool_calls"].append(
                        ToolCall(
                            id=current_tool_use["id"],
                            name=current_tool_use["name"],
                            arguments=arguments,
                        )
                    )
                state["content"] = state.get("content", "")
                state["reasoning"] = reasoning_buffer
                raise _StreamInterruptedError(state) from exc
            raise

        if finish_reason:
            yield StreamChunk(finish_reason=finish_reason, usage=pending_usage)


# ---------------------------------------------------------------------------
# 续传 / 重试辅助
# ---------------------------------------------------------------------------


class _StreamInterruptedError(Exception):
    """流式响应因可恢复网络错误中断，携带当前已累积状态。"""

    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state


def _is_retriable_stream_error(exc: Exception) -> bool:
    """判断异常是否为流式传输过程中可恢复的网络错误。"""
    retriable_types: tuple[type[Exception], ...] = (
        anthropic.APIConnectionError,
        anthropic.APITimeoutError,
        anthropic.InternalServerError,
    )
    if isinstance(exc, retriable_types):
        return True
    if isinstance(exc, (httpx.ReadError, httpx.ConnectError, httpx.TimeoutException)):
        return True
    if isinstance(exc, (httpcore.ReadError, httpcore.ConnectError, httpcore.ConnectTimeout)):
        return True
    return False


def _build_resume_messages(
    original_messages: list[dict[str, Any]],
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    """根据已收状态构造续传 messages（Anthropic 格式）。

    在原消息列表后追加 assistant 消息（包含已生成的 thinking / text /
    tool_use content blocks），再追加一条 user 提示让 LLM 从断点继续。
    """
    messages: list[dict[str, Any]] = list(original_messages)
    assistant_content: list[dict[str, Any]] = []

    # thinking block 优先放在最前面（与 Anthropic 原始输出顺序一致）
    reasoning = state.get("reasoning")
    if reasoning:
        assistant_content.append({
            "type": "thinking",
            "thinking": reasoning,
            "signature": "",
        })

    content = state.get("content")
    if content:
        assistant_content.append({"type": "text", "text": content})

    for tc in state.get("completed_tool_calls", []):
        assistant_content.append({
            "type": "tool_use",
            "id": tc.id,
            "name": tc.name,
            "input": tc.arguments,
        })

    if not assistant_content:
        assistant_content.append({"type": "text", "text": " "})

    messages.append({"role": "assistant", "content": assistant_content})

    from system.templates import read_template
    messages.append({
        "role": "user",
        "content": [{"type": "text", "text": read_template("llm/stream_resume.txt")}],
    })
    return messages


# ---------------------------------------------------------------------------
# 工具 schema 转换
# ---------------------------------------------------------------------------


def _openai_tools_to_anthropic(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """将 OpenAI 格式工具 schema 转换为 Anthropic 格式。"""
    anthropic_tools: list[dict[str, Any]] = []
    for tool in tools:
        if tool.get("type") != "function":
            continue
        function = tool.get("function", {}) or {}
        name = function.get("name", "")
        if not name:
            continue
        anthropic_tools.append({
            "name": name,
            "description": function.get("description", ""),
            "input_schema": _ensure_input_schema(function.get("parameters", {})),
        })
    return anthropic_tools


def _ensure_input_schema(parameters: Any) -> dict[str, Any]:
    """确保 Anthropic input_schema 顶层为 JSON Schema object。"""
    if not isinstance(parameters, dict):
        return {"type": "object"}
    schema = dict(parameters)
    if schema.get("type") is None:
        schema["type"] = "object"
    return schema


# ---------------------------------------------------------------------------
# 响应解析
# ---------------------------------------------------------------------------


def _parse_message(response: Any) -> LLMResponse:
    """从 Anthropic Message 对象解析 LLMResponse。"""
    content = ""
    reasoning_content = ""
    tool_calls: list[ToolCall] = []

    for block in response.content or []:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            content += getattr(block, "text", "") or ""
        elif block_type == "thinking":
            reasoning_content += getattr(block, "thinking", "") or ""
        elif block_type == "tool_use":
            tool_calls.append(_parse_tool_use_block(block))

    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        finish_reason=_map_stop_reason(getattr(response, "stop_reason", None)),
        reasoning_content=reasoning_content or None,
        reasoning_field_name="reasoning_content" if reasoning_content else None,
        usage=_extract_usage(response),
    )


def _parse_tool_use_block(block: Any) -> ToolCall:
    """将 Anthropic tool_use block 解析为 ToolCall。"""
    tc_id = getattr(block, "id", "")
    name = getattr(block, "name", "")
    input_dict = getattr(block, "input", {}) or {}
    if not isinstance(input_dict, dict):
        input_dict = {}
    return ToolCall(id=tc_id, name=name, arguments=input_dict)


def _map_stop_reason(stop_reason: Any) -> str:
    """将 Anthropic stop_reason 映射为 OpenAI 兼容的 finish_reason。"""
    if stop_reason == "end_turn":
        return "stop"
    if stop_reason == "tool_use":
        return "tool_calls"
    if stop_reason == "max_tokens":
        return "length"
    return stop_reason or "stop"


def _extract_usage(obj: Any) -> Usage:
    """从 Anthropic Message / MessageDelta 中提取 token 消耗。"""
    if obj is None:
        return Usage()
    usage = getattr(obj, "usage", None)
    if usage is None:
        return Usage()
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    return Usage(
        prompt_tokens=input_tokens,
        completion_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
    )


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------


def _safe_json_parse(raw: str) -> dict[str, Any]:
    """安全解析 JSON 字符串，失败时返回带错误信息的 dict。"""
    if isinstance(raw, str) and raw.strip() == "":
        return {}

    try:
        result = dirtyjson.loads(raw)
        if isinstance(result, dict):
            return result
    except Exception as exc:
        logger.warning(
            "Failed to parse Anthropic tool use input (%d chars): %s: %s",
            len(raw),
            type(exc).__name__,
            exc,
        )
        return {
            "_parse_error": True,
            "_parse_error_type": type(exc).__name__,
            "_parse_error_msg": str(exc),
            "_raw_preview": raw[:TOOL_RESULT_PREVIEW_CHARS],
        }

    logger.warning(
        "Failed to parse Anthropic tool use input (%d chars): %s ...",
        len(raw),
        raw[:300],
    )
    return {
        "_parse_error": True,
        "_raw_preview": raw[:TOOL_RESULT_PREVIEW_CHARS],
    }


# ---------------------------------------------------------------------------
# 模块工厂
# ---------------------------------------------------------------------------


def create_llm_client(
    runtime_context: RuntimeContext,
    profile: dict[str, Any] | None = None,
) -> AnthropicLLMClient:
    """按 RuntimeContext 或 profile 构造 Anthropic LLM 客户端。

    *profile* 为 None 时直接使用 *runtime_context*；否则从 *profile* 读取配置，
    缺失字段回退到 *runtime_context*。
    """
    if profile is None:
        return AnthropicLLMClient.from_context(runtime_context)

    return AnthropicLLMClient(
        api_key=profile.get("api_key")
        or runtime_context.llm_api_key
        or os.environ.get("ANTHROPIC_API_KEY", ""),
        base_url=profile.get("base_url", runtime_context.llm_base_url),
        model=profile.get("model", runtime_context.llm_model),
        temperature=profile.get("temperature", runtime_context.llm_temperature),
        max_output_tokens=profile.get(
            "max_output_tokens", runtime_context.llm_max_output_tokens
        ),
    )