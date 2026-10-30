"""Session export business exception types."""

from __future__ import annotations

from typing import Literal


class SessionExportError(ValueError):
    """导出边界的已识别业务拒绝；服务层复用而不建立循环依赖。"""

    def __init__(
        self,
        code: str,
        message: str,
        status: int = 400
        ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class SessionExportInputError(SessionExportError):
    """请求结构、路径或来源无效。"""

    def __init__(
        self,
        code: str,
        message: str
        ) -> None:
        super().__init__(code, message, 400)


class SessionExportNotFoundError(SessionExportError):
    """会话不存在、删除中或目标资源缺失。"""

    def __init__(
        self,
        code: str,
        message: str
        ) -> None:
        super().__init__(code, message, 404)


class SessionExportNotReadyError(SessionExportError):
    """会话存在但 Loop 未恢复、身份不匹配或已归档不可导出。"""

    def __init__(
        self,
        code: str,
        message: str
        ) -> None:
        super().__init__(code, message, 409)


class SessionExportCapacityError(SessionExportError):
    """进程级并发容量已满，不排队直接拒绝。"""

    def __init__(self) -> None:
        super().__init__("export_capacity", "Too many concurrent export operations", 429)


class SessionExportMetricsError(SessionExportError):
    """消息计时文件已存在但结构损坏；不能转成空 metrics。"""

    def __init__(self, message: str) -> None:
        super().__init__("invalid_metrics", message, 409)


class SessionExportLimitError(SessionExportError):
    def __init__(self, message: str) -> None:
        super().__init__("export_limit", message, 413)


class SessionExportChangedError(SessionExportError):
    def __init__(self) -> None:
        super().__init__("export_changed", "Session content changed; retry when idle", 409)


class SessionExportTimeoutError(SessionExportError):
    def __init__(self) -> None:
        super().__init__("export_timeout", "Export operation timed out; retry when idle", 408)


class SessionExportBusyError(SessionExportError):
    def __init__(self) -> None:
        super().__init__("session_busy", "Session must be idle before exporting", 409)


class _SourceUnavailable(Exception):
    """线程侧资源不可用信号；由 status 与 code 承载结果。"""

    def __init__(
        self,
        status: Literal["missing", "denied", "too_large"],
        code: str
        ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
