"""Agentspace 编辑器使用的纯数据类型。"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class AgentspaceEntryKind(str, Enum):
    FILE = "file"
    DIR = "dir"


class AgentspaceEventKind(str, Enum):
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    MOVED = "moved"
    LOCKS = "locks"
    TRASH_CHANGED = "trash_changed"
    RESYNC = "resync"
    WATCHER_ERROR = "watcher_error"


class AgentspaceEventSource(str, Enum):
    SERVICE = "service"
    WATCHER = "watcher"
    LOCKS = "locks"
    SYSTEM = "system"


class AgentspaceTrashState(str, Enum):
    READY = "ready"
    RECOVERABLE = "recoverable"
    CORRUPT = "corrupt"


class AgentspaceEntry(BaseModel):
    name: str
    path: str
    kind: AgentspaceEntryKind


class AgentspacePathIdentity(BaseModel):
    display_path: str
    canonical_key: str


class AgentspaceFileSnapshot(BaseModel):
    path: str
    content: str
    version: str
    size: int
    modified_ns: int


class AgentspaceLockOwner(BaseModel):
    owner_id: str
    session_id: str
    character_name: str
    round_id: str


class AgentspaceLockInfo(BaseModel):
    path: str
    recursive: bool = False
    owners: list[AgentspaceLockOwner] = Field(default_factory=list)


class AgentspaceEvent(BaseModel):
    sequence: int = 0
    kind: AgentspaceEventKind
    source: AgentspaceEventSource = AgentspaceEventSource.SYSTEM
    path: str | None = None
    new_path: str | None = None
    is_directory: bool | None = None
    locks: list[AgentspaceLockInfo] | None = None
    timestamp: str
    operation_id: str | None = None
    version: str | None = None
    message: str | None = None


class AgentspaceTrashEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: str
    state: AgentspaceTrashState = AgentspaceTrashState.READY
    original_path: str | None = None
    name: str | None = None
    kind: AgentspaceEntryKind | None = None
    deleted_at: str | None = None
    size: int = 0
    error: str | None = None


class AgentspaceWriteRequest(BaseModel):
    path: str
    content: str
    expected_version: str | None = None
    operation_id: str = ""


class AgentspacePathRequest(BaseModel):
    path: str
    operation_id: str = ""


class AgentspaceRenameRequest(BaseModel):
    path: str
    new_name: str
    operation_id: str = ""
