"""Translate only declared domain refusals to structured HTTP errors."""

from typing import NoReturn

from fastapi import HTTPException

from entity.constant import GatewayErrorCode
from entity.error import (
    AgentspaceAlreadyExistsError, AgentspaceError, AgentspaceInvalidPathError,
    AgentspaceLockedError, AgentspaceNotFoundError, AgentspaceNotTextError,
    AgentspaceVersionConflictError, DynamicSandboxConflictError,
    DynamicSandboxInputError, DynamicSandboxNotFoundError,
    MetadataGenerationError, MetadataProfileUnavailableError, SandboxError,
    SessionVariableAccessError, SessionVariableConflictError,
    SessionVariableError, SessionVariableLimitError,
)
from gateway.http_boundary import business_http_error


def raise_metadata_http(
    exc: MetadataProfileUnavailableError | MetadataGenerationError,
) -> NoReturn:
    unavailable = isinstance(exc, MetadataProfileUnavailableError)
    raise business_http_error(
        409 if unavailable else 502,
        GatewayErrorCode.METADATA_PROFILE_UNAVAILABLE if unavailable
        else GatewayErrorCode.METADATA_GENERATION_FAILED,
        str(exc),
    ) from exc


def raise_sandbox_space_http(
    exc: DynamicSandboxInputError | DynamicSandboxNotFoundError | SandboxError,
) -> NoReturn:
    if isinstance(exc, DynamicSandboxNotFoundError):
        status, code = 404, GatewayErrorCode.SANDBOX_SPACE_NOT_FOUND
    elif isinstance(exc, DynamicSandboxConflictError):
        status, code = 409, GatewayErrorCode.SANDBOX_SPACE_CONFLICT
    elif isinstance(exc, SandboxError):
        status, code = 400, GatewayErrorCode.SANDBOX_ACCESS_DENIED
    else:
        status, code = 400, GatewayErrorCode.SANDBOX_INPUT_INVALID
    raise business_http_error(status, code, str(exc)) from exc


def raise_agentspace_http(exc: AgentspaceError) -> NoReturn:
    if isinstance(exc, AgentspaceInvalidPathError):
        status = 400
    elif isinstance(exc, AgentspaceNotFoundError):
        status = 404
    elif isinstance(exc, (AgentspaceAlreadyExistsError, AgentspaceVersionConflictError)):
        status = 409
    elif isinstance(exc, AgentspaceNotTextError):
        status = 415
    elif isinstance(exc, AgentspaceLockedError):
        status = 423
    else:
        status = 400
    # 已有详情中显式null、版本和锁字段原样保留。
    raise HTTPException(status_code=status, detail=exc.as_detail()) from exc


def raise_variable_http(exc: SessionVariableError) -> NoReturn:
    if isinstance(exc, SessionVariableAccessError):
        status = 403
    elif isinstance(exc, SessionVariableLimitError):
        status = 413
    elif isinstance(exc, SessionVariableConflictError):
        status = 409
    else:
        status = 400
    raise business_http_error(
        status, exc.code, str(exc), details={"path": exc.logical_path},
    ) from exc
