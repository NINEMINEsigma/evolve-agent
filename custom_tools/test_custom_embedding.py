"""测试 embedding 工具 — 传入两段文本，返回余弦相似度。

用于验证 llamaapis embedding 端点是否跑通。
启动一个独立的 llama-server 实例，通过 RuntimeContext 获取 embedding 模型配置，
加载 custom_models 中指定的模型，对两段文本分别获取向量，计算余弦相似度后卸载。
"""

from __future__ import annotations

import logging
import math
from typing import * # type: ignore

from abstract.tools.registry import registry, tool_result
from entity.puretype import ToolDangerLevel

if TYPE_CHECKING:
    from entry.base_agent_loop import ToolContext

logger = logging.getLogger(__name__)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度。"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _handle_test_custom_embedding(args: dict[str, Any], context: ToolContext | None = None) -> dict:
    """对两段文本分别生成 embedding，返回余弦相似度。"""
    text1 = args["text1"]
    text2 = args["text2"]

    if context is None:
        return tool_result(success=False, message="ToolContext is required")

    # ── 从 RuntimeContext 获取 embedding 模型配置 ──
    ctx = context.runtime_context
    model_name = ctx.embedding_model.strip()
    if not model_name:
        return tool_result(success=False, message="embedding_model is not configured (empty string in RuntimeContext)")

    cuda = ctx.embedding_model_cuda
    port = ctx.embedding_model_port

    try:
        from entity.constant import Namespace
        from system.application import Application
        from third.llamaapis import InferenceEngine, ModelConfig
    except Exception as exc:
        return tool_result(success=False, message=f"Import failed: {exc}")

    # ── 定位模型文件 ──
    models_dir = Application.current().sandbox.get_base(Namespace.CUSTOM_MODELS)
    model_path = models_dir / model_name

    if not model_path.is_file():
        return tool_result(success=False, message=f"Model file not found: {model_path}")

    # ── 启动引擎并获取 embedding ──
    engine: InferenceEngine | None = None
    try:
        engine = InferenceEngine(ModelConfig(
            model_path=str(model_path),
            n_ctx=2048,
            n_gpu_layers=-1 if cuda else 0,
            cuda=cuda,
            port=port,
            flash_attn=cuda,
            auto_build=True,
            embedding=True,
        ))
        # 一次性提交两条文本，减少一轮往返
        resp = engine.embedding([text1, text2])
        vec1 = resp.data[0].embedding if len(resp.data) > 0 else []
        vec2 = resp.data[1].embedding if len(resp.data) > 1 else []
        similarity = _cosine_similarity(vec1, vec2)
        return tool_result(
            success=True,
            model=str(model_path.name),
            dimensions=len(vec1),
            similarity=round(similarity, 6),
            text1_preview=text1[:100],
            text2_preview=text2[:100],
        )
    except Exception as exc:
        logger.exception("test_custom_embedding failed")
        return tool_result(success=False, message=f"Embedding failed: {exc}")
    finally:
        if engine is not None:
            engine.unload()


# ── 注册 ─────────────────────────────────────────────────────

registry.register(
    name="test_custom_embedding",
    toolset="embedding_test",
    schema={
        # 对两段文本分别生成 embedding 向量，计算余弦相似度。
        # 从 RuntimeContext 读取 embedding_model / embedding_model_cuda / embedding_model_port 配置，
        # 启动独立的 llama-server 实例（--embedding 模式），加载 custom_models 中指定的 GGUF 模型，
        # 一次性提交两条文本到 /v1/embeddings 端点。
        # 返回余弦相似度（-1 ~ 1，越接近 1 越相似）。
        # 前置条件：config.json 中配置了 embedding_model，且对应文件存在于 custom_models/。
        # 副作用：启动并终止一个 llama-server 子进程。
        "description": """Compute the semantic similarity between two texts using embedding vectors.

## Prerequisites
`embedding_model` must be configured in config.json and the corresponding GGUF file must exist in custom_models/.

## Parameters
- text1: The first text to compare.
- text2: The second text to compare.

## Returns
```json
{ "success": true, "model": "...", "dimensions": 1024, "similarity": 0.87, "text1_preview": "...", "text2_preview": "..." }
```
The similarity is a cosine similarity score ranging from -1 to 1. A value closer to 1 means the two texts are semantically more similar.

## Side Effects
Starts and stops a llama-server subprocess (port from embedding_model_port config).""",
        "parameters": {
            "type": "object",
            "properties": {
                "text1": {
                    "type": "string",
                    # 第一段待比较的文本。
                    "description": """The first text to compare.""",
                },
                "text2": {
                    "type": "string",
                    # 第二段待比较的文本。
                    "description": """The second text to compare.""",
                },
            },
            "required": ["text1", "text2"],
        },
    },
    handler=_handle_test_custom_embedding,
    is_async=False,
    danger_level=ToolDangerLevel.readonly,
)