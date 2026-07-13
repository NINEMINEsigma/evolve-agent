"""LLM 客户端抽象层。

定义 ``BaseLLMClient`` 抽象基类，统一所有 LLM 后端（OpenAI、本地模型等）
的调用接口。具体实现应继承此类并提供 ``chat`` 和 ``chat_stream`` 方法。
"""

from __future__ import annotations

from abstract.llm.client import BaseLLMClient

__all__ = ["BaseLLMClient"]