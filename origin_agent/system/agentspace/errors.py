"""Agentspace 领域异常；不依赖 FastAPI。"""

from __future__ import annotations

from typing import Any


class AgentspaceError(Exception):
    code = "agentspace_error"

    def __init__(self, message: str, *, path: str | None = None, **details: Any) -> None:
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
        current_version: str | None,
    ) -> None:
        super().__init__(
            message,
            path=path,
            current_version=current_version,
        )
        self.current_version = current_version


class AgentspaceLockedError(AgentspaceError):
    code = "path_locked"

    def __init__(self, message: str, *, path: str, locks: list[dict[str, Any]]) -> None:
        super().__init__(message, path=path, locks=locks)
        self.locks = locks


class AgentspaceTrashError(AgentspaceError):
    code = "trash_error"


class AgentspaceTrashCorruptError(AgentspaceTrashError):
    code = "trash_corrupt"
