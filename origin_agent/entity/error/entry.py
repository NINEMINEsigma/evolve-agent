"""Entry-layer business exceptions."""


class IncompatibleHistoryError(Exception):
    """会话历史格式不兼容，无法加载。"""
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"Session {session_id} history format is incompatible")


class ToolInterrupted(Exception):
    """内部中断信号：可中断等待被 cancel_event 打断时抛出。

    携带 phase 字段（"approval" / "dispatch"），由调用方
    ``except ToolInterrupted as ti`` 捕获后用 ``ti.phase``
    构造统一的中断失败结果。
    """

    def __init__(self, phase: str) -> None:
        super().__init__(f"Tool call interrupted during {phase}")
        self.phase: str = phase


class HistoryMediaNotFoundError(LookupError):
    """媒体实例已不存在，不能按原历史位置猜测另一个实例。"""


class HistoryMediaConflictError(ValueError):
    """客户端所见开关与服务端当前值发生并发冲突。"""


class HistoryMediaPreviewError(ValueError):
    def __init__(
        self,
        message: str,
        status_code: int
        ) -> None:
        if status_code not in (400, 415):
            raise ValueError("Invalid media preview error status")
        super().__init__(message)
        self.status_code = status_code


class ModalityForwardUnavailableError(ValueError):
    """活动模型不支持该模态且未配置任何引用 Profile，无法转发。

    携带面向用户的配置指引（配置对应媒体引用 Profile 或切换到支持
    该模态的模型）。调用方捕获后应终止本轮回复并将指引作为持久化
    系统状态展示给前端。
    """
