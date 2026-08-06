"""审批后端抽象与实现 — 脱手模式 LLM 审批的引擎层。

包含：
- ApprovalBackend 抽象基类
- LocalApprovalBackend（本地 GGUF，通过 llama-server 推理）
- RemoteApprovalBackend（远程 OpenAI 兼容 API）
- 后端工厂函数
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, TYPE_CHECKING

from entity.constant import (
    APPROVAL_MODEL_LOAD_TIMEOUT,
    APPROVAL_LOCAL_DISABLED_VALUES,
    APPROVAL_JSON_SCHEMA_CACHE_FILENAME,
    APPROVAL_RESPONSE_FORMAT_NAME,
    CUSTOM_MODELS_DIR,
)
from entity.messages import BaseMessage
from entity.puretype import Role

if TYPE_CHECKING:
    from abstract.llm.client import BaseLLMClient
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
            if role == Role.SYSTEM.value:
                internal_messages.append(system_message(content))
            else:
                internal_messages.append(user_message(content))

        config = GenerationConfig(temperature=0.3, thinking=False)
        if json_schema is not None:
            config.json_schema = json_schema
        resp = await asyncio.to_thread(engine.chat, internal_messages, config)
        return resp.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# 远程审批后端 — json_schema 能力缓存
# ---------------------------------------------------------------------------


def _json_schema_cache_path(ctx: RuntimeContext) -> Path:
    """返回 json_schema 能力缓存文件路径。"""
    return ctx.workspace / APPROVAL_JSON_SCHEMA_CACHE_FILENAME


def _json_schema_cache_key(base_url: str, client_name: str, model: str) -> str:
    """构造缓存键：base_url|client_name|model。"""
    return f"{base_url}|{client_name}|{model}"


def _is_json_schema_unsupported(ctx: RuntimeContext, base_url: str, client_name: str, model: str) -> bool:
    """读取缓存，判断该 base_url+client_name+model 组合是否已知不支持 json_schema。"""
    try:
        path = _json_schema_cache_path(ctx)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get(_json_schema_cache_key(base_url, client_name, model)) is False
    except Exception:
        logger.warning("Failed to read json_schema capability cache", exc_info=True)
    return False


def _mark_json_schema_unsupported(ctx: RuntimeContext, base_url: str, client_name: str, model: str) -> None:
    """将该组合标记为不支持 json_schema，写入缓存。"""
    try:
        path = _json_schema_cache_path(ctx)
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, bool] = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        data[_json_schema_cache_key(base_url, client_name, model)] = False
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Failed to save json_schema capability cache: %s", exc)


def _is_json_schema_rejection(exc: Exception) -> bool:
    """判断异常是否为服务端拒绝 json_schema（400/422）。"""
    # 检查 status_code 属性（兼容 openai.APIStatusError / anthropic.APIStatusError）
    status_code = getattr(exc, "status_code", None)
    if status_code in (400, 422):
        return True
    # 兼容 httpx.HTTPStatusError（status_code 在 exc.response.status_code）
    response = getattr(exc, "response", None)
    if response is not None:
        status_code = getattr(response, "status_code", None)
        if status_code in (400, 422):
            return True
    # 兜底：检查错误消息中的关键词
    msg = str(exc).lower()
    return any(k in msg for k in ("json_schema", "response_format", "unsupported response format"))


# ---------------------------------------------------------------------------
# 远程审批后端（基于 custom_llm_client 插件）
# ---------------------------------------------------------------------------

class RemoteApprovalBackend(ApprovalBackend):
    """基于 custom_llm_client 插件的远程审批后端。

    通过 create_llm_client() 加载指定的 LLM 客户端插件，
    将 ApprovalBackend.chat() 接口适配为 BaseLLMClient.chat() 调用。
    """

    def __init__(self, ctx: RuntimeContext) -> None:
        self._ctx = ctx
        self._client: BaseLLMClient | None = None

    def _get_client(self) -> BaseLLMClient:
        if self._client is None:
            from abstract.llm.loader import create_llm_client
            profile = {
                "api_key": self._ctx.approval_remote_api_key,
                "base_url": self._ctx.approval_remote_base_url,
                "model": self._ctx.approval_remote_model,
                "temperature": 0.3,
            }
            self._client = create_llm_client(
                self._ctx.approval_remote_client_name, self._ctx, profile
            )
        return self._client

    async def is_available(self) -> bool:
        return bool(self._ctx.approval_remote_base_url and self._ctx.approval_remote_model)

    async def chat(self, messages: list[dict[str, Any]], json_schema: dict[str, Any] | None = None) -> str:
        client = self._get_client()
        base_messages = [
            BaseMessage(role=Role(m.get("role", "user")), content=m.get("content", ""))
            for m in messages
        ]

        # json_schema → response_format 转换
        response_format: dict[str, Any] | None = None
        if json_schema is not None:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": APPROVAL_RESPONSE_FORMAT_NAME,
                    "schema": json_schema,
                    "strict": True,
                },
            }

        # 缓存检查：若已知不支持 json_schema 则跳过
        if response_format is not None:
            base_url = self._ctx.approval_remote_base_url
            client_name = self._ctx.approval_remote_client_name
            model = self._ctx.approval_remote_model
            if _is_json_schema_unsupported(self._ctx, base_url, client_name, model):
                logger.info("json_schema known unsupported for %s|%s|%s — skipping", base_url, client_name, model)
                response_format = None

        try:
            resp = await client.chat(base_messages, response_format=response_format)
            return resp.content or ""
        except Exception as exc:
            if response_format is not None and _is_json_schema_rejection(exc):
                logger.warning(
                    "Remote approval backend rejected json_schema — falling back to plain chat: %s", exc
                )
                _mark_json_schema_unsupported(
                    self._ctx,
                    self._ctx.approval_remote_base_url,
                    self._ctx.approval_remote_client_name,
                    self._ctx.approval_remote_model,
                )
                resp = await client.chat(base_messages)
                return resp.content or ""
            raise


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------

_ENGINE_FAILED = object()


def is_local_approval_enabled(ctx: RuntimeContext) -> bool:
    """判定当前是否启用本地审批模型。"""
    raw = (ctx.approval_model_path or "").strip().lower()
    return raw not in APPROVAL_LOCAL_DISABLED_VALUES


def create_approval_backend(ctx: RuntimeContext) -> ApprovalBackend | None:
    """根据 RuntimeContext 创建对应的审批后端。"""
    if is_local_approval_enabled(ctx):
        return LocalApprovalBackend(ctx)
    if ctx.approval_remote_base_url and ctx.approval_remote_model:
        return RemoteApprovalBackend(ctx)
    return None