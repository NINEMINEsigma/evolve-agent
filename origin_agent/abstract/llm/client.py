"""LLM 客户端抽象基类。

``BaseLLMClient`` 声明所有 LLM 后端必须支持的 ``chat`` 和 ``chat_stream`` 接口。
构造函数由各具体实现自行定义，抽象层不依赖 ``RuntimeContext``，以保持后端无关。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, Optional

from entity.messages import BaseMessage
from entity.puretype import LLMResponse, StreamChunk


class BaseLLMClient(ABC):
    """LLM 客户端抽象基类。

    提供两种调用方式：
      - ``chat()``：非流式，返回完整 ``LLMResponse``
      - ``chat_stream()``：流式，逐块 yield ``StreamChunk``

    具体实现类负责处理认证、重试、流式消费、错误恢复等后端细节。

    子类必须实现 ``_convert_messages()`` 将 ``list[BaseMessage]``
    转换为对应 LLM 后端的 wire format。
    """

    @abstractmethod
    async def chat(
        self,
        messages: list[BaseMessage],
        tools: Optional[list[dict[str, Any]]] = None,
        response_format: Optional[dict[str, str]] = None,
        character: str = "",
    ) -> LLMResponse:
        """发送聊天请求，返回完整结构化响应。

        *messages* 为 ``BaseMessage`` 对象列表，子类在发送前自行转换为 wire format。
        *tools* 为可选的 OpenAI 格式工具 schema 列表。
        *response_format* 用于指定结构化输出格式（如 json_object）。
        *character* 当前运行中的 agent 角色名，用于 ``as_message()`` 内的可见性过滤和前缀修饰。
        """
        raise NotImplementedError

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[BaseMessage],
        tools: Optional[list[dict[str, Any]]] = None,
        response_format: Optional[dict[str, str]] = None,
        character: str = "",
    ) -> AsyncIterator[StreamChunk]:
        """发送流式聊天请求，逐块返回增量内容。

        实现应支持 content 增量、reasoning 增量、tool_calls 累积输出，
        并在流结束时发出带 ``finish_reason`` 的 chunk。

        *character* 当前运行中的 agent 角色名，用于 ``as_message()`` 内的可见性过滤和前缀修饰。
        """
        raise NotImplementedError
        yield None  # noqa