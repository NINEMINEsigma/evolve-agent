"""测试 embedding 检索工具 — 传入一段文本，从当前会话历史中检索最相似的消息。

用于验证 embedding 异步更新 + 历史检索的完整链路。
通过 EmbeddingBackendManager 获取查询文本的向量，
再与当前会话历史中所有 CharacterConversationMessage 的已存储向量计算余弦相似度，
返回相似度最高的前 5 条。
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


def _extract_text(content: Any) -> str:
    """从 CharacterConversationMessage.content 提取纯文本预览。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif hasattr(block, "text"):
                parts.append(getattr(block, "text", ""))
        return "\n".join(parts)
    return str(content)


async def _handle_test_custom_embedding(args: dict[str, Any], context: ToolContext | None = None) -> dict:
    """对查询文本生成 embedding，从当前会话历史中检索最相似的消息。"""
    query_text = args["text"]

    if context is None:
        return tool_result(success=False, message="ToolContext is required")

    try:
        from system.application import Application
        from entity.messages import CharacterConversationMessage
    except Exception as exc:
        return tool_result(success=False, message=f"Import failed: {exc}")

    # ── 通过 EmbeddingBackendManager 获取 embedding 后端 ──
    app = Application.current()
    backend = await app.embedding_backend_manager.get_backend()
    if backend is None:
        return tool_result(success=False, message="Embedding backend not available (embedding_model not configured or engine failed)")

    # ── 获取查询文本的 embedding ──
    resp = await backend.embed([query_text])
    if resp is None or not resp:
        return tool_result(success=False, message="Failed to generate embedding for query text")
    query_vec = resp[0]

    # ── 遍历会话历史，计算相似度 ──
    history = context.loop.history
    results: list[dict[str, Any]] = []

    for index, msg in enumerate(history.iter_messages()):
        if not isinstance(msg, CharacterConversationMessage):
            continue

        stored_vec = msg.get_embedding(backend.model_name)
        if stored_vec is None:
            continue

        similarity = _cosine_similarity(query_vec, stored_vec)
        text_preview = _extract_text(msg.content)[:200]

        results.append({
            "index": index,
            "similarity": round(similarity, 6),
            "role": msg.role.value,
            "character": msg.character_name,
            "preview": text_preview,
        })

    # ── 按相似度降序，取前 5 ──
    results.sort(key=lambda x: x["similarity"], reverse=True)
    top5 = results[:5]

    return tool_result(
        success=True,
        model=backend.model_name,
        dimensions=len(query_vec),
        query_preview=query_text[:100],
        total_with_embedding=len(results),
        results=top5,
    )


# ── 注册 ─────────────────────────────────────────────────────

registry.register(
    name="test_custom_embedding",
    toolset="embedding_test",
    schema={
        # 传入一段文本，通过 EmbeddingBackendManager 获取其 embedding 向量，
        # 然后遍历当前会话历史中所有 CharacterConversationMessage 的已存储向量，
        # 计算余弦相似度并按降序排列，返回最相似的前 5 条。
        # 仅匹配已有相同 embedding_model 的消息；尚未完成嵌入计算的消息会被跳过。
        # 前置条件：config.json 中配置了 embedding_model，且对应文件存在于 custom_models/。
        # 依赖：EmbeddingBackendManager 已通过 Application.init() 初始化。
        "description": """Search the current session history for messages semantically similar to the query text.

## Prerequisites
`embedding_model` must be configured in config.json and the embedding backend must be available.

## Parameters
- text: The query text to search for.

## Returns
```json
{
  "success": true,
  "model": "bge-large-zh-v1.5-q4_k_m.gguf",
  "dimensions": 1024,
  "query_preview": "...",
  "total_with_embedding": 15,
  "results": [
    { "index": 3, "similarity": 0.87, "role": "user", "character": "User", "preview": "..." },
    ...
  ]
}
```
Results are sorted by cosine similarity (descending), limited to top 5.
Messages without a stored embedding vector are skipped.""",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    # 待检索的查询文本。
                    "description": """The query text to search for in session history.""",
                },
            },
            "required": ["text"],
        },
    },
    handler=_handle_test_custom_embedding,
    is_async=True,
    danger_level=ToolDangerLevel.safe,
)