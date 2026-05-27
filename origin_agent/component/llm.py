"""OpenAI 兼容的 LLM 客户端。

使用 ``openai`` SDK。配置来自 RuntimeContext
（api_key、base_url、model、temperature、max_tokens），
密钥通过环境变量兜底（``OPENAI_API_KEY``）。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import openai
from pydantic import BaseModel, ConfigDict

from system.context import RuntimeContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 响应类型
# ---------------------------------------------------------------------------


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    arguments: Dict[str, Any] = {}


class Usage(BaseModel):
    """LLM 提供商返回的 token 消耗。"""
    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str = ""
    tool_calls: List[ToolCall] = []
    finish_reason: str = "stop"
    reasoning_content: Optional[str] = None
    """DeepSeek thinking-mode 载荷 — 在后续回合中必须回传。"""
    usage: Usage = Usage()


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
            base_url=ctx.llm_base_url or "https://api.openai.com/v1",
        )
        self._model: str = ctx.llm_model or "gpt-4o"
        self._temperature: float = ctx.llm_temperature
        self._max_tokens: int = ctx.llm_max_output_tokens

    # -- 公开 API ----------------------------------------------------------

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        """发送聊天请求，返回结构化响应。

        *messages* 为 OpenAI 格式的消息字典列表
        （``{"role": "...", "content": "..."}``）。
        *tools* 为可选的 OpenAI 格式工具 schema 列表。

        返回包含 assistant 内容和工具调用的 :class:`LLMResponse`。
        """
        kwargs: Dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        if tools:
            kwargs["tools"] = tools

        completion: Any = await self._client.chat.completions.create(**kwargs)
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
            reasoning_content=getattr(msg, "reasoning_content", None),
            usage=Usage(
                prompt_tokens=completion.usage.prompt_tokens if completion.usage else 0,
                completion_tokens=completion.usage.completion_tokens if completion.usage else 0,
                total_tokens=completion.usage.total_tokens if completion.usage else 0,
            ),
        )


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------


def _safe_json_parse(raw: str) -> Dict[str, Any]:
    import dirtyjson

    try:
        result = dirtyjson.loads(raw)
        if isinstance(result, dict):
            return result
    except Exception:
        pass

    logger.warning(
        "Failed to parse tool call arguments (%d chars): %s …",
        len(raw), raw[:300],
    )
    return {"_parse_error": True, "_raw_preview": raw[:2000]}