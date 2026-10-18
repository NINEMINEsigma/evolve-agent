"""成功文件目标操作的消息前纯类型；时间仅存 UTC 字符串。"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

FileChangeKind = Literal["file", "directory"]
FileChangeDisplayState = Literal["created", "modified", "deleted"]
FileChangeAction = Literal["create", "modify", "delete", "copy", "move"]
FileChangeToolName = Literal["Write", "PatchEdit", "Delete", "Copy", "Move"]
NonnegativeCount = Annotated[int, Field(strict=True, ge=0)]
PositiveCount = Annotated[int, Field(strict=True, ge=1)]
NonemptyText = Annotated[str, Field(strict=True, min_length=1)]


class SessionFileChangeActor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: NonemptyText
    character_name: NonemptyText


class SessionFileChangeOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_name: FileChangeToolName
    operation: FileChangeAction
    path: NonemptyText
    kind: FileChangeKind
    source_path: str | None = None
    destination_path: str | None = None


class SessionFileChangeEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: NonemptyText
    kind: FileChangeKind
    display_state: FileChangeDisplayState
    created_by_session: StrictBool
    operation_count: PositiveCount
    last_operation: FileChangeAction
    last_tool_name: FileChangeToolName
    actors: list[SessionFileChangeActor]
    last_operated_at: NonemptyText
    last_revision: PositiveCount
    source_path: str | None = None
    destination_path: str | None = None


class SessionFileChangesData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: NonemptyText
    revision: NonnegativeCount = 0
    entries: dict[str, SessionFileChangeEntry] = Field(default_factory=dict)


class SessionFileChangesSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: NonemptyText
    revision: NonnegativeCount
    file_count: NonnegativeCount
    directory_count: NonnegativeCount
    operation_count: NonnegativeCount
    last_operated_at: str | None


class SessionFileChangesPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: SessionFileChangesSummary
    offset: NonnegativeCount
    limit: PositiveCount
    total_count: NonnegativeCount
    items: list[SessionFileChangeEntry]
