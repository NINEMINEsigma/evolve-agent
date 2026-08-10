"""Embedding 后端抽象与实现 — 语义向量计算的引擎层。

包含：
- EmbeddingBackend 抽象基类
- LocalEmbeddingBackend（本地 GGUF，通过 llama-server --embedding 推理）
- EmbeddingBackendManager（懒加载 + 生命周期管理）
- 后端工厂函数
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from system.context import RuntimeContext
    from third.llamaapis import InferenceEngine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 哨兵对象，标记引擎初始化失败（与 LocalApprovalBackend 一致）
# ---------------------------------------------------------------------------
_ENGINE_FAILED = object()


# ---------------------------------------------------------------------------
# EmbeddingBackend 抽象
# ---------------------------------------------------------------------------

class EmbeddingBackend(ABC):
    """语义向量嵌入后端抽象。"""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]] | None:
        """批量计算 embedding 向量。失败返回 None。"""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """后端当前是否可用。"""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """当前 embedding 模型标识（用于回写到消息的 embedding_model 字段）。"""
        ...


# ---------------------------------------------------------------------------
# 本地 GGUF 后端
# ---------------------------------------------------------------------------

class LocalEmbeddingBackend(EmbeddingBackend):
    """基于 llama.cpp / llama-server 的本地 embedding 后端。"""

    def __init__(self, ctx: RuntimeContext) -> None:
        self._ctx = ctx
        self._engine: InferenceEngine | None | object = None  # object sentinel for failed

    def _get_engine(self) -> InferenceEngine | None:
        """懒加载本地 embedding 引擎。失败标记 _ENGINE_FAILED。"""
        if self._engine is _ENGINE_FAILED:
            return None
        if self._engine is not None:
            return self._engine  # type: ignore[return-value]

        try:
            from system.application import Application
            from entity.constant import Namespace
            from third.llamaapis import InferenceEngine as LlamaEngine, ModelConfig

            model_path = str(
                Application.current().sandbox.get_base(Namespace.CUSTOM_MODELS) / self._ctx.embedding_model.strip()
            )
            cuda = bool(self._ctx.embedding_model_cuda)
            n_gpu_layers = -1 if cuda else 0

            self._engine = LlamaEngine(ModelConfig(
                model_path=model_path,
                n_ctx=2048,
                n_gpu_layers=n_gpu_layers,
                cuda=cuda,
                port=int(self._ctx.embedding_model_port),
                flash_attn=cuda,
                auto_build=True,
                embedding=True,
            ))
            logger.info("Local embedding backend loaded | model=%s cuda=%s", model_path, cuda)
            return self._engine
        except Exception as exc:
            logger.exception("Failed to initialize local embedding backend: %s", exc)
            self._engine = _ENGINE_FAILED
            return None

    @property
    def model_name(self) -> str:
        return self._ctx.embedding_model

    async def is_available(self) -> bool:
        engine = self._get_engine()
        if engine is None:
            return False
        if not engine.is_model_loaded():
            if not engine.ensure_alive():
                return False
            # 引擎刚重启，轮询等待模型加载
            for _ in range(120):
                await asyncio.sleep(1.0)
                if engine.is_model_loaded():
                    return True
            return False
        return True

    async def embed(self, texts: list[str]) -> list[list[float]] | None:
        engine = self._get_engine()
        if engine is None:
            return None
        try:
            resp = await asyncio.to_thread(engine.embedding, texts)
            return [d.embedding for d in resp.data]
        except Exception as exc:
            logger.exception("Local embedding failed: %s", exc)
            return None


# ---------------------------------------------------------------------------
# 管理器 — 懒加载 + 生命周期
# ---------------------------------------------------------------------------

class EmbeddingBackendManager:
    """管理 embedding 后端的懒加载和生命周期。

    与 ApprovalBackendManager 模式一致：构造后不立即初始化，
    首次 get_backend() 时懒加载并检查可用性。
    """

    def __init__(self, ctx: RuntimeContext) -> None:
        self._ctx = ctx
        self._backend: EmbeddingBackend | None = None
        self._failed: bool = False

    async def get_backend(self) -> EmbeddingBackend | None:
        """懒加载 embedding 后端。返回 None 表示不可用。"""
        if self._failed:
            return None
        if self._backend is not None:
            return self._backend

        self._backend = create_embedding_backend(self._ctx)
        if self._backend is None:
            self._failed = True
            return None

        if not await self._backend.is_available():
            logger.warning("Embedding backend not available — embedding updates will be skipped")
            self._failed = True
            self._backend = None
            return None

        return self._backend

    async def shutdown(self) -> None:
        """停止 embedding 引擎子进程并释放资源。"""
        if self._backend is None:
            return
        try:
            if isinstance(self._backend, LocalEmbeddingBackend):
                engine = self._backend._get_engine()
                if engine is not None:
                    engine.unload()
                    logger.info("Embedding backend unloaded successfully")
        except Exception as exc:
            logger.warning("Failed to unload embedding backend: %s", exc)
        self._backend = None
        self._failed = False


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------

def create_embedding_backend(ctx: RuntimeContext) -> EmbeddingBackend | None:
    """根据 RuntimeContext 创建对应的 embedding 后端。"""
    if ctx.embedding_model.strip():
        return LocalEmbeddingBackend(ctx)
    return None