"""LLM 客户端抽象基类。

``BaseLLMClient`` 声明所有 LLM 后端必须支持的 ``chat`` 和 ``chat_stream`` 接口。
构造函数由各具体实现自行定义，抽象层不依赖 ``RuntimeContext``，以保持后端无关。

客户端必须忠实转换收到的多模态内容块；无法表达某种模态时必须抛出异常，
禁止静默删除、用普通文本替换或伪造成功。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from entity.messages import BaseMessage, CharacterConversationMessage
from entity.puretype import LLMResponse, StreamChunk


class UnsupportedModalityError(RuntimeError):
    """LLM 客户端无法忠实表达输入多模态内容块。"""


class LLMEmptyResponseError(RuntimeError):
    """LLM 空响应重试耗尽，或只有未完成工具增量而没有有效响应。"""


class LLMAPIStatusError(RuntimeError):
    """客户端 API 状态错误的统一 abstract 层表达，携带 HTTP ``status_code``。

    客户端把各自 SDK 的 ``APIStatusError`` 归一化为本异常：非流式路径由
    客户端直接转换抛出（``raise ... from`` 保留原始异常链）；流式回退
    收集路径（如 ``chat()`` 的流式回退分支）经 ``StreamChunk.error`` +
    ``StreamChunk.error_code`` 重建。上层（探针/转发）只需识别本类型，
    不依赖任何具体 SDK 的异常族。
    """

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class BaseLLMClient(ABC):
    """LLM 客户端抽象基类。

    提供两种调用方式：
      - ``chat()``：非流式，返回完整 ``LLMResponse``
      - ``chat_stream()``：流式，逐块 yield ``StreamChunk``

    具体实现类负责处理认证、重试、流式消费、错误恢复等后端细节。
    对 ``ImageBlock``、``AudioBlock``、``VideoBlock`` 等多模态内容，
    实现必须完整转换并发送；无法支持时必须抛出异常，禁止静默降级。

    子类必须实现 ``_convert_messages()`` 将 ``list[BaseMessage]``
    转换为对应 LLM 后端的 wire format。
    """

    @abstractmethod
    async def chat(
        self,
        messages: list[BaseMessage],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, str] | None = None,
        character: str = "",
        *,
        last_user_message: CharacterConversationMessage | None = None,
    ) -> LLMResponse:
        """发送聊天请求，返回完整结构化响应。

        *messages* 为 ``BaseMessage`` 对象列表，子类在发送前自行转换为 wire format。
        *tools* 为可选的 OpenAI 格式工具 schema 列表。
        *response_format* 用于指定结构化输出格式（如 json_object）。
        *character* 当前运行中的 agent 角色名，用于消息转换时的可见性过滤和前缀修饰（发送前由 LLM 客户端自行调用 ``to_openai_message()``）。
        *last_user_message* 用于标记 ``is_last_user_message``，使 ``dynamic_message_suffix`` 被附加。

        多模态内容块必须完整转换并发送；无法支持时必须抛出异常，禁止静默删除、
        文本占位或伪造成功。
        """
        raise NotImplementedError

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[BaseMessage],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, str] | None = None,
        character: str = "",
        *,
        last_user_message: CharacterConversationMessage | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """发送流式聊天请求，逐块返回增量内容。

        实现应支持 content 增量、reasoning 增量、tool_calls 累积输出，
        并在流结束时发出带 ``finish_reason`` 的 chunk。
        返回的异步迭代器必须支持 ``aclose()``；消费侧负责关闭外层流，
        客户端装饰器负责在退出或重试之前关闭其持有的底层流。

        *character* 当前运行中的 agent 角色名，用于消息转换时的可见性过滤和前缀修饰（发送前由 LLM 客户端自行调用 ``to_openai_message()``）。
        *last_user_message* 用于标记 ``is_last_user_message``，使 ``dynamic_message_suffix`` 被附加。

        多模态内容块必须完整转换并发送；无法支持时必须抛出异常，禁止静默删除、
        文本占位或伪造成功。
        """
        raise NotImplementedError
        yield None  # noqa