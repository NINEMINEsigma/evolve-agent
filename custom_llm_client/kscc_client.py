"""金山云(KSCC)代理的 Anthropic 兼容 LLM 客户端。

与标准 :class:`AnthropicLLMClient` 的区别：
  - 使用 ``Authorization: Bearer <token>`` 认证（而非 ``x-api-key``）
  - 携带 KSCC 特有的请求头（``x-ksc-company-code``、``ksyun-code-type`` 等）
  - 请求路径附带 ``?beta=true`` 查询参数

其余行为（重试、流式续传、工具解析、usage 提取）与父类完全一致。
"""

from __future__ import annotations

import os
from typing import Any, Optional

import anthropic

from entity.puretype import LLMResponse, StreamChunk
from system.context import RuntimeContext

from custom_llm_client.anthropic_client import AnthropicLLMClient


# ---------------------------------------------------------------------------
# KSCC 专用常量
# ---------------------------------------------------------------------------

# KSCC 代理要求的固定请求头（不含 Authorization，该头在 __init__ 中动态拼接）
_KSCC_FIXED_HEADERS: dict[str, str] = {
    "x-ksc-company-code": "seasun",
    "ksyun-code-type": "kscc-cli",
    "ksyun-code-version": "1.1.20",
    "User-Agent": "claude-cli/1.1.20 (external, cli)",
    "Accept": "application/json",
}

# 附加在 messages 端点上的查询参数
_KSCC_EXTRA_QUERY: dict[str, str] = {"beta": "true"}


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------


class KSCCAnthropicLLMClient(AnthropicLLMClient):
    """金山云(KSCC)代理的 Anthropic 兼容客户端。

    继承 :class:`AnthropicLLMClient` 的全部公开接口（``chat`` / ``chat_stream``），
    仅覆写 ``__init__`` 和 ``_build_kwargs`` 以适配 KSCC 代理的认证与请求格式。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float,
        max_output_tokens: int,
    ) -> None:
        # 不调用 super().__init__()——父类会用 api_key 创建 x-api-key 认证，
        # 而 KSCC 代理需要 Bearer token 认证，因此在此直接构造 SDK 客户端。
        default_headers: dict[str, str] = {
            "Authorization": f"Bearer {api_key}",
            **_KSCC_FIXED_HEADERS,
        }

        self._client: anthropic.AsyncAnthropic = anthropic.AsyncAnthropic(
            api_key="dummy",          # 占位，阻止SDK从环境变量读取
            base_url=base_url,
            default_headers=default_headers,
        )
        self._model: str = model
        self._temperature: float = temperature
        self._max_tokens: int = max_output_tokens

    @classmethod
    def from_context(cls, ctx: RuntimeContext) -> KSCCAnthropicLLMClient:
        """从 RuntimeContext 构造 KSCC Anthropic 客户端。"""
        return cls(
            api_key=ctx.llm_api_key or os.environ.get("KSCC_AUTH_TOKEN", ""),
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
        """在父类参数基础上追加 KSCC 专用查询参数。"""
        kwargs = super()._build_kwargs(messages, system, tools, stream)
        kwargs["extra_query"] = dict(_KSCC_EXTRA_QUERY)
        return kwargs


# ---------------------------------------------------------------------------
# 模块工厂
# ---------------------------------------------------------------------------


def create_kscc_llm_client(
    runtime_context: RuntimeContext,
    profile: dict[str, Any] | None = None,
) -> KSCCAnthropicLLMClient:
    """按 RuntimeContext 或 profile 构造 KSCC Anthropic LLM 客户端。

    *profile* 为 None 时直接使用 *runtime_context*；否则从 *profile* 读取配置，
    缺失字段回退到 *runtime_context*。
    """
    if profile is None:
        return KSCCAnthropicLLMClient.from_context(runtime_context)

    return KSCCAnthropicLLMClient(
        api_key=profile.get("api_key")
        or runtime_context.llm_api_key
        or os.environ.get("KSCC_AUTH_TOKEN", ""),
        base_url=profile.get("base_url", runtime_context.llm_base_url),
        model=profile.get("model", runtime_context.llm_model),
        temperature=profile.get("temperature", runtime_context.llm_temperature),
        max_output_tokens=profile.get(
            "max_output_tokens", runtime_context.llm_max_output_tokens
        ),
    )