"""离线导出的非持久化 HTTP 纯类型，不依赖正式消息模型。"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from entity.constant.session_export import (
    SESSION_EXPORT_ARCHIVE_INPUT_MAX_BYTES, SESSION_EXPORT_DEPENDENCY_MAX_DEPTH,
    SESSION_EXPORT_FORMAT_VERSION, SESSION_EXPORT_HISTORY_MAX_BYTES,
    SESSION_EXPORT_MAX_MESSAGES, SESSION_EXPORT_MAX_NODES,
    SESSION_EXPORT_MAX_RESOURCES, SESSION_EXPORT_MAX_ROWS,
    SESSION_EXPORT_REQUEST_TIMEOUT_SECONDS, SESSION_EXPORT_RESOURCE_MAX_BYTES,
    SESSION_EXPORT_RESOURCE_TOTAL_MAX_BYTES, SESSION_EXPORT_SNAPSHOT_MAX_BYTES,
    SESSION_EXPORT_STRUCTURE_MAX_DEPTH, SESSION_EXPORT_TOTAL_TIMEOUT_SECONDS,
    SESSION_EXPORT_VERIFY_BODY_MAX_BYTES,
)
from .session import SessionHistoryContentRow


ExportDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class SessionExportStamp(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    loop_instance_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    export_epoch: int = Field(ge=0)
    history_digest: ExportDigest
    metadata_digest: ExportDigest
    visual_digest: ExportDigest


class SessionExportHistorySnapshot(BaseModel):
    loop_instance_id: str
    export_epoch: int
    history_digest: ExportDigest
    history_count: int = Field(ge=0)
    rows: list[SessionHistoryContentRow]


class SessionExportVisualEntry(BaseModel):
    kind: Literal["stage", "chat_style"]
    status: Literal["ready", "missing", "error"]
    configured: bool
    availability: Literal[
        "unconfigured", "ready", "missing_entry", "invalid_metadata", "unreadable"
    ]
    source_path: str
    effective_path: str
    entry_path: str | None = None
    error_code: str | None = None


class SessionExportLimits(BaseModel):
    max_history_bytes: int = SESSION_EXPORT_HISTORY_MAX_BYTES
    max_snapshot_bytes: int = SESSION_EXPORT_SNAPSHOT_MAX_BYTES
    max_messages: int = SESSION_EXPORT_MAX_MESSAGES
    max_rows: int = SESSION_EXPORT_MAX_ROWS
    max_nodes: int = SESSION_EXPORT_MAX_NODES
    max_structure_depth: int = SESSION_EXPORT_STRUCTURE_MAX_DEPTH
    max_resource_bytes: int = SESSION_EXPORT_RESOURCE_MAX_BYTES
    max_resource_total_bytes: int = SESSION_EXPORT_RESOURCE_TOTAL_MAX_BYTES
    max_resources: int = SESSION_EXPORT_MAX_RESOURCES
    max_depth: int = SESSION_EXPORT_DEPENDENCY_MAX_DEPTH
    max_verify_body_bytes: int = SESSION_EXPORT_VERIFY_BODY_MAX_BYTES
    max_archive_input_bytes: int = SESSION_EXPORT_ARCHIVE_INPUT_MAX_BYTES
    request_timeout_seconds: int = SESSION_EXPORT_REQUEST_TIMEOUT_SECONDS
    total_timeout_seconds: int = SESSION_EXPORT_TOTAL_TIMEOUT_SECONDS


class SessionExportSnapshotResponse(BaseModel):
    format_version: Literal[1] = SESSION_EXPORT_FORMAT_VERSION
    session_id: str
    captured_at: str
    title: str
    tags: list[str]
    history_count: int = Field(ge=0)
    rows: list[SessionHistoryContentRow]
    stamp: SessionExportStamp
    visuals: list[SessionExportVisualEntry]
    limits: SessionExportLimits = Field(default_factory=SessionExportLimits)


class SessionExportResourceSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    kind: Literal["sandbox", "local_font"]
    path: str = Field(min_length=1, max_length=4096)


class SessionExportResourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    stamp: SessionExportStamp
    source: SessionExportResourceSource


class SessionExportResourceProof(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source: SessionExportResourceSource
    status: Literal["saved", "missing", "denied", "too_large"]
    digest: ExportDigest | None = None
    size: int | None = Field(default=None, ge=0)
    identity: ExportDigest | None = None


class SessionExportVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    stamp: SessionExportStamp
    resources: list[SessionExportResourceProof] = Field(
        max_length=SESSION_EXPORT_MAX_RESOURCES
    )


class SessionExportVerifyResponse(BaseModel):
    session_id: str
    verified: Literal[True] = True
    verified_at: str


class SessionExportResourceIssue(BaseModel):
    code: str
    source: SessionExportResourceSource
    proof: SessionExportResourceProof | None = None
