"""Anthropic 兼容的 LLM 客户端。

提供两个接口：
  - ``chat()`` — 非流式请求，返回完整 :class:`LLMResponse`
  - ``chat_stream()`` — 流式请求，逐块 yield :class:`StreamChunk`

使用 ``anthropic`` SDK。配置来自 RuntimeContext
（api_key、base_url、model、temperature、max_output_tokens），
密钥通过环境变量兜底（``ANTHROPIC_API_KEY``）。

 Anthropic 协议没有原生的 ``reasoning_content`` / ``response_format`` 字段，
 因此 reasoning 字段不传入 Anthropic，``response_format`` 在本实现中忽略。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import AsyncIterator
from typing import Any, Optional

import anthropic
import dirtyjson

from abstract.llm.client import BaseLLMClient
from abstract.llm.formats import messages_to_openai_list
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
        openai_messages = messages_to_openai_list(
            messages, current_character_agent=character
        )
        anthropic_messages, system = _openai_messages_to_anthropic(openai_messages)
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

        支持 content 增量、tool_use 的完整输出，并在流结束时发出带
        ``finish_reason`` 的 chunk。出现可恢复网络错误时按配置次数重试。
        """
        openai_messages = messages_to_openai_list(
            messages, current_character_agent=character
        )
        anthropic_messages, system = _openai_messages_to_anthropic(openai_messages)
        anthropic_tools = _openai_tools_to_anthropic(tools) if tools else None
        kwargs = self._build_kwargs(
            anthropic_messages, system, anthropic_tools, stream=True
        )

        has_yielded = False
        for attempt in range(LLM_RETRY_COUNT):
            try:
                stream = await self._client.messages.create(**kwargs)
                async with stream:
                    async for chunk in self._consume_one_stream(stream):
                        has_yielded = True
                        yield chunk
                return
            except (
                anthropic.APIConnectionError,
                anthropic.APITimeoutError,
                anthropic.RateLimitError,
                anthropic.InternalServerError,
            ) as exc:
                if not has_yielded and attempt < LLM_RETRY_COUNT - 1:
                    wait: float = BACKOFF_BASE * (2 ** attempt)
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
    ) -> AsyncIterator[StreamChunk]:
        """消费单条 Anthropic 流，产出增量并返回结束状态。

        Anthropic 流事件类型：message_start / content_block_start /
        content_block_delta / content_block_stop / message_delta / message_stop。
        """
        current_tool_use: dict[str, Any] | None = None
        pending_tool_input: str = ""
        finish_reason: str | None = None
        pending_usage: Usage | None = None

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
                if block is not None and getattr(block, "type", None) == "tool_use":
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
                        yield StreamChunk(content_delta=text)
                elif delta_type == "tool_use_delta":
                    partial = getattr(delta, "partial_json", "") or ""
                    pending_tool_input += partial

            elif event_type == "content_block_stop":
                if current_tool_use is not None:
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

        if finish_reason:
            yield StreamChunk(finish_reason=finish_reason, usage=pending_usage)


# ---------------------------------------------------------------------------
# 消息 / 工具转换
# ---------------------------------------------------------------------------


def _openai_messages_to_anthropic(
    openai_messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    """将 OpenAI 格式消息转换为 Anthropic Messages API 格式。

    Anthropic 要求：
      - system 提示只能作为顶层 ``system`` 参数，不能穿插在 messages 中。
      - 工具调用结果（tool_result）必须放在 user 消息的 content 列表里。
      - 助手消息的 tool_calls 需要转换为 ``tool_use`` content block。
    """
    system_parts: list[str] = []
    anthropic_messages: list[dict[str, Any]] = []
    pending_tool_results: list[dict[str, Any]] = []

    def _flush_tool_results() -> None:
        nonlocal pending_tool_results
        if pending_tool_results:
            anthropic_messages.append({
                "role": "user",
                "content": pending_tool_results,
            })
            pending_tool_results = []

    for msg in openai_messages:
        role = msg.get("role")
        content = msg.get("content")

        if role == "system":
            system_parts.extend(_extract_text_from_content(content))
            continue

        if role == "tool":
            pending_tool_results.append(_build_tool_result_block(msg))
            continue

        _flush_tool_results()

        anthropic_content = _openai_content_to_anthropic(content)
        if role == "assistant":
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                for tc in tool_calls:
                    anthropic_content.append(_tool_call_to_tool_use(tc))

        if not anthropic_content:
            # Anthropic 不接受空 content 的消息，跳过
            continue

        anthropic_messages.append({
            "role": role,
            "content": anthropic_content,
        })

    _flush_tool_results()

    system = "\n\n".join(system_parts) if system_parts else ""
    return anthropic_messages, system


def _extract_text_from_content(content: Any) -> list[str]:
    """从 OpenAI  content 中提取文本片段。"""
    if isinstance(content, str):
        return [content] if content.strip() else []
    if isinstance(content, list):
        texts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if text:
                    texts.append(text)
        return texts
    return []


def _openai_content_to_anthropic(content: Any) -> list[dict[str, Any]]:
    """将 OpenAI 的字符串或 content block 列表转换为 Anthropic content block 列表。"""
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []

    if isinstance(content, list):
        blocks: list[dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                text = block.get("text", "")
                if text:
                    blocks.append({"type": "text", "text": text})
            elif block_type == "image_url":
                image_url = block.get("image_url", {})
                url = image_url.get("url", "") if isinstance(image_url, dict) else ""
                image_block = _image_url_to_anthropic_image(url)
                if image_block is not None:
                    blocks.append(image_block)
        return blocks

    return []


def _image_url_to_anthropic_image(url: str) -> dict[str, Any] | None:
    """将 OpenAI image_url 转换为 Anthropic image block。"""
    if not url:
        return None

    # 支持 base64 data URL，例如 data:image/png;base64,...
    if url.startswith("data:"):
        match = re.match(r"data:([^;]+);base64,(.+)", url)
        if match:
            media_type = match.group(1)
            data = match.group(2)
            return {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": data,
                },
            }
        return None

    return {
        "type": "image",
        "source": {"type": "url", "url": url},
    }


def _build_tool_result_block(msg: dict[str, Any]) -> dict[str, Any]:
    """将 OpenAI tool 消息转换为 Anthropic tool_result block。"""
    content = msg.get("content")
    anthropic_content: Any
    if isinstance(content, list):
        anthropic_content = _openai_content_to_anthropic(content)
    elif isinstance(content, str):
        anthropic_content = content
    else:
        anthropic_content = ""

    return {
        "type": "tool_result",
        "tool_use_id": msg.get("tool_call_id", ""),
        "content": anthropic_content,
    }


def _tool_call_to_tool_use(tc: dict[str, Any]) -> dict[str, Any]:
    """将 OpenAI tool_call 转换为 Anthropic tool_use block。"""
    tc_id = tc.get("id", "")
    function = tc.get("function", {}) or {}
    name = function.get("name", "")
    arguments = function.get("arguments", "{}") or "{}"
    return {
        "type": "tool_use",
        "id": tc_id,
        "name": name,
        "input": _safe_json_parse(arguments),
    }


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
    tool_calls: list[ToolCall] = []

    for block in response.content or []:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            content += getattr(block, "text", "") or ""
        elif block_type == "tool_use":
            tool_calls.append(_parse_tool_use_block(block))

    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        finish_reason=_map_stop_reason(getattr(response, "stop_reason", None)),
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