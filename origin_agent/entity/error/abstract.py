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

    def __init__(
        self,
        message: str,
        status_code: int
        ) -> None:
        super().__init__(message)
        self.status_code = status_code


class InvalidMcpUrlError(ValueError):
    """Raised when a remote MCP server's ``url`` cannot be parsed as http(s)://.

    Validated once at startup so we fail fast with a clear message instead of
    burning through the reconnect-backoff loop on every attempt.  (Ported from
    anomalyco/opencode#25019.)
    """


class OAuthNonInteractiveError(RuntimeError):
    """Raised when OAuth requires browser interaction in a non-interactive env."""
