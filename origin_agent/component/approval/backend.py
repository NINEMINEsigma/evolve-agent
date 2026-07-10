"""审批后端抽象与实现 — 脱手模式 LLM 审批的引擎层。

包含：
- ApprovalBackend 抽象基类
- LocalApprovalBackend（本地 GGUF，通过 llama-server 推理）
- RemoteApprovalBackend（远程 OpenAI 兼容 API）
- 后端工厂函数
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

import openai
from openai.types.chat import ChatCompletion

from entity.constant import APPROVAL_MODEL_LOAD_TIMEOUT, CUSTOM_MODELS_DIR

if TYPE_CHECKING:
    from third.llamaapis import InferenceEngine
    from system.context import RuntimeContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ApprovalBackend 抽象
# ---------------------------------------------------------------------------

class ApprovalBackend(ABC):
    """脱手模式审批后端抽象。"""

    @abstractmethod
    async def chat(self, messages: list[dict[str, Any]], json_schema: dict[str, Any] | None = None) -> str:
        """发送对话请求，返回模型生成的文本。"""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """后端当前是否可用。"""
        ...


class FailedApprovalBackend(ApprovalBackend):
    """哨兵子类，表示审批后端已尝试初始化但失败。"""

    async def is_available(self) -> bool:
        return False

    async def chat(self, messages: list[dict[str, Any]], json_schema: dict[str, Any] | None = None) -> str:
        raise RuntimeError("Approval backend is in failed state")


# ---------------------------------------------------------------------------
# 本地 GGUF 后端
# ---------------------------------------------------------------------------

class LocalApprovalBackend(ApprovalBackend):
    """基于 llama.cpp / llama-server 的本地审批后端。"""

    def __init__(self, ctx: RuntimeContext) -> None:
        self._ctx = ctx
        self._engine: InferenceEngine | None | object = None  # object sentinel for failed

    def _get_engine(self) -> InferenceEngine | None:
        """懒加载本地审批引擎。"""
        if self._engine is _ENGINE_FAILED:
            return None
        if self._engine is not None:
            return self._engine  # type: ignore[return-value]

        try:
            from system.pathutils import find_repo_root
            from third.llamaapis import InferenceEngine as LlamaEngine, ModelConfig

            root = find_repo_root()
            model_path = str((root / CUSTOM_MODELS_DIR / self._ctx.approval_model_path.strip()).resolve())
            cuda = bool(self._ctx.approval_model_cuda)
            n_gpu_layers = -1 if cuda else 0

            self._engine = LlamaEngine(ModelConfig(
                model_path=model_path,
                n_ctx=int(self._ctx.approval_model_n_ctx),
                n_gpu_layers=n_gpu_layers,
                cuda=cuda,
                port=int(self._ctx.approval_model_port),
                flash_attn=cuda,
                auto_build=True,
            ))
            logger.info("Local approval backend loaded | model=%s cuda=%s", model_path, cuda)
            return self._engine
        except Exception as exc:
            logger.exception("Failed to initialize local approval backend: %s", exc)
            self._engine = _ENGINE_FAILED
            return None

    async def is_available(self) -> bool:
        engine = self._get_engine()
        if engine is None:
            return False
        if not engine.is_model_loaded():
            if not engine.ensure_alive():
                return False
            for _ in range(APPROVAL_MODEL_LOAD_TIMEOUT):
                await asyncio.sleep(1.0)
                if engine.is_model_loaded():
                    return True
            return False
        return True

    async def chat(self, messages: list[dict[str, Any]], json_schema: dict[str, Any] | None = None) -> str:
        from third.llamaapis import GenerationConfig, system_message, user_message

        engine = self._get_engine()
        if engine is None:
            raise RuntimeError("Local approval engine not available")

        internal_messages = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                internal_messages.append(system_message(content))
            else:
                internal_messages.append(user_message(content))

        config = GenerationConfig(temperature=0.3, thinking=False)
        if json_schema is not None:
            config.json_schema = json_schema
        resp = await asyncio.to_thread(engine.chat, internal_messages, config)
        return resp.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# 远程 OpenAI 兼容后端
# ---------------------------------------------------------------------------

class RemoteApprovalBackend(ApprovalBackend):
    """基于 OpenAI 兼容 API 的远程审批后端（如 LM Studio）。"""

    def __init__(self, ctx: RuntimeContext) -> None:
        self._ctx = ctx
        self._client: openai.AsyncOpenAI | None = None

    def _get_client(self) -> openai.AsyncOpenAI:
        if self._client is None:
            api_key = self._ctx.approval_remote_api_key or ""
            base_url = self._ctx.approval_remote_base_url or ""
            self._client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
        return self._client

    async def is_available(self) -> bool:
        return bool(self._ctx.approval_remote_base_url and self._ctx.approval_remote_model)

    async def chat(self, messages: list[dict[str, Any]], json_schema: dict[str, Any] | None = None) -> str:
        client = self._get_client()
        model: str = self._ctx.approval_remote_model
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.3,
        }
        if json_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "approval_decision",
                    "schema": json_schema,
                    "strict": True,
                },
            }

        try:
            resp: ChatCompletion = await client.chat.completions.create(**kwargs)
        except openai.APIStatusError as exc:
            # 若服务端不支持 json_schema（如部分旧 LM Studio），回退到普通请求
            if json_schema is not None and exc.status_code in (400, 422):
                logger.warning(
                    "Remote approval backend rejected json_schema (status=%s) — falling back to plain chat",
                    exc.status_code,
                )
                kwargs.pop("response_format", None)
                resp = await client.chat.completions.create(**kwargs)
            else:
                raise

        if not resp.choices:
            raise RuntimeError("Remote approval backend returned empty choices")
        return resp.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------

_ENGINE_FAILED = object()
_LOCAL_DISABLED_VALUES: set[str] = {"", "false", "0", "no"}


def is_local_approval_enabled(ctx: RuntimeContext) -> bool:
    """判定当前是否启用本地审批模型。"""
    raw = (ctx.approval_model_path or "").strip().lower()
    return raw not in _LOCAL_DISABLED_VALUES


def create_approval_backend(ctx: RuntimeContext) -> ApprovalBackend | None:
    """根据 RuntimeContext 创建对应的审批后端。"""
    if is_local_approval_enabled(ctx):
        return LocalApprovalBackend(ctx)
    if ctx.approval_remote_base_url and ctx.approval_remote_model:
        return RemoteApprovalBackend(ctx)
    return None