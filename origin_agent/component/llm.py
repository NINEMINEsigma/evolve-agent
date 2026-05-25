"""OpenAI-compatible LLM client.

Uses the ``openai`` SDK.  Configuration comes from RuntimeContext
(api_key, base_url, model, temperature, max_tokens) with env-var
fallback for secrets (``OPENAI_API_KEY``).
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
# Response types
# ---------------------------------------------------------------------------


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    arguments: Dict[str, Any] = {}


class Usage(BaseModel):
    """Token usage returned by the LLM provider."""
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
    """DeepSeek thinking-mode payload — must be echoed on subsequent turns."""
    usage: Usage = Usage()


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class LLMClient:
    """Thin wrapper around the OpenAI SDK.

    Parameters are taken from the RuntimeContext's LLM fields.
    ``api_key`` falls back to the ``OPENAI_API_KEY`` env var.
    """

    def __init__(self, ctx: RuntimeContext) -> None:
        api_key = ctx.llm_api_key or os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            logger.warning(
                "No LLM API key configured — set OPENAI_API_KEY env var "
                "or pass it via RuntimeContext"
            )

        self._client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=ctx.llm_base_url or "https://api.openai.com/v1",
        )
        self._model = ctx.llm_model or "gpt-4o"
        self._temperature = ctx.llm_temperature
        self._max_tokens = ctx.llm_max_tokens

    # -- public API ----------------------------------------------------------

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        """Send a chat request and return a structured response.

        *messages* is a list of OpenAI-format message dicts
        (``{"role": "...", "content": "..."}``).
        *tools* is an optional list of OpenAI-format tool schemas.

        Returns an :class:`LLMResponse` with the assistant's content
        and any tool calls.
        """
        kwargs: Dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        if tools:
            kwargs["tools"] = tools

        completion = await self._client.chat.completions.create(**kwargs)
        choice = completion.choices[0]
        msg = choice.message

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
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_json_parse(raw: str) -> Dict[str, Any]:
    import json

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Failed to parse tool call arguments: %s", raw[:200])
        return {}