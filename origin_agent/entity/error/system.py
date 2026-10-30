"""System and Agentspace domain exception types."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from entity.puretype.resource_cleanup import CleanupWarning


class ShellError(RuntimeError):
    """Shell会话操作失败。"""


class ShellAccessError(ShellError):
    """Shell会话不存在或调用者无权访问。"""


class ModalityDescriptionError(RuntimeError):
    """转发返回空描述等协议失败，不能当作明确模态不可用。"""


class SandboxError(PermissionError):
    """当工具操作违反沙盒约束时抛出。"""


class DynamicSandboxInputError(ValueError):
    """动态沙盒空间名称、路径或描述等业务输入无效时抛出。

    Gateway 捕获后映射 HTTP 400。内部类型不变量（如字段非字符串/布尔）
    仍抛 ``TypeError``，不在此类中。
    """


class DynamicSandboxConflictError(DynamicSandboxInputError):
    """动态沙盒空间名称重复、同名配置不同或路径与已有空间/内置命名空间重叠时抛出。

    Gateway 捕获后映射 HTTP 409（比 ``DynamicSandboxInputError`` 更具体，优先匹配）。
    """


class DynamicSandboxNotFoundError(KeyError):
    """按名称更新动态沙盒空间但目标不存在时抛出。

    Gateway 捕获后映射 HTTP 404。
    """


class SessionMetadataError(RuntimeError):
    """可预期的会话元数据业务失败。"""


class MetadataProfileUnavailableError(SessionMetadataError):
    """没有可用的全局或目标会话 Profile。"""


class MetadataGenerationError(SessionMetadataError):
    """元数据模型调用或输出解析失败。"""


class ProfileNotFoundError(LookupError):
    """指定名称的 LLM Profile 不存在（可预期的用户请求错误）。"""


class ProfileConflictError(ValueError):
    """LLM Profile 名称冲突或引用占用导致拒绝操作（可预期的用户请求错误）。"""


class ResourceCleanupTimeout(TimeoutError):
    """A located cleanup phase exhausted its observation deadline."""

    def __init__(self, warning: CleanupWarning) -> None:
        self.warning = warning
        super().__init__(warning.message)


class ResourceCleanupPendingError(RuntimeError):
    """A new operation conflicts with a resource that is still being released."""


class LifecycleFailure(RuntimeError):
    """生命周期约定被破坏或资源未在期限内结束。"""


class ApplicationStoppingError(RuntimeError):
    """应用已停止接收新的业务工作。"""


class HistoryPersistenceError(LifecycleFailure):
    """History 写盘失败；保留原始 cause，禁止被普通工具错误吞没。

    继承 ``LifecycleFailure``，使所有涉及本次提交的宽泛捕获（如
    ``except Exception``）仍能通过 ``contains_lifecycle_failure`` 识别
    并让该错误继续传播，不被转换为成功的应用关闭。
    """

    def __init__(
        self,
        session_id: str,
        cause: BaseException
        ) -> None:
        super().__init__(
            f"Failed to persist history for session {session_id}: {cause}"
        )
        self.__cause__ = cause


class RipgrepUnavailable(RuntimeError):
    """固定 ripgrep 二进制不可用，可回退到 Python 搜索。"""


class RipgrepRecoverableError(RuntimeError):
    """本次 ripgrep 调用失败，但整次回退可保持结果完整性。"""


class RipgrepFatalError(RuntimeError):
    """不应静默回退的 ripgrep 错误。"""


class SessionVariableError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        logical_path: str = ""
        ) -> None:
        super().__init__(message)
        self.code = code
        self.logical_path = logical_path


class SessionVariableInputError(SessionVariableError):
    pass


class SessionVariableAccessError(SessionVariableError):
    pass


class SessionVariableLimitError(SessionVariableError):
    def __init__(
        self,
        message: str,
        *,
        logical_path: str = ""
        ) -> None:
        super().__init__(message, code="pool_limit_exceeded", logical_path=logical_path)


class SessionVariableConflictError(SessionVariableError):
    def __init__(
        self,
        message: str,
        *,
        logical_path: str = ""
        ) -> None:
        super().__init__(message, code="pool_conflict", logical_path=logical_path)


class SessionVariableCleanupFailure(LifecycleFailure):
    pass


class SessionVisualResourceError(ValueError):
    """安全的入口错误，不包含物理路径。"""


class SessionVisualVersionUnavailable(SessionVisualResourceError):
    """签名预算耗尽或资源在扫描中失效；不能返回部分签名。"""


class SessionFileChangesPersistenceFailure(LifecycleFailure):
    """文件副作用已完成后，必要统计提交失败。"""


class SessionFileChangesBusyError(RuntimeError):
    """删除尚未开始，会话统计提交锁在允许期限内仍被占用。"""


class AgentspaceError(Exception):
    code = "agentspace_error"

    def __init__(
        self,
        message: str,
        *,
        path: str | None = None,
        **details: Any
        ) -> None:
        super().__init__(message)
        self.message = message
        self.path = path
        self.details = details

    def as_detail(self) -> dict[str, Any]:
        detail: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.path is not None:
            detail["path"] = self.path
        detail.update(self.details)
        return detail


class AgentspaceInvalidPathError(AgentspaceError):
    code = "invalid_path"


class AgentspaceNotFoundError(AgentspaceError):
    code = "not_found"


class AgentspaceNotTextError(AgentspaceError):
    code = "not_text"


class AgentspaceAlreadyExistsError(AgentspaceError):
    code = "already_exists"


class AgentspaceVersionConflictError(AgentspaceError):
    code = "version_conflict"

    def __init__(
        self,
        message: str,
        *,
        path: str,
        current_version: str | None
        ) -> None:
        super().__init__(
            message,
            path=path,
            current_version=current_version,
        )
        self.current_version = current_version


class AgentspaceLockedError(AgentspaceError):
    code = "path_locked"

    def __init__(
        self,
        message: str,
        *,
        path: str,
        locks: list[dict[str, Any]]
        ) -> None:
        super().__init__(message, path=path, locks=locks)
        self.locks = locks


class AgentspaceTrashError(AgentspaceError):
    code = "trash_error"


class AgentspaceTrashCorruptError(AgentspaceTrashError):
    code = "trash_corrupt"
