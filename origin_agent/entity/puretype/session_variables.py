"""会话变量池响应和非持久化继承材料；只含字段。"""

from typing import Literal, TypeAlias
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr

SessionVariableFileIdentity: TypeAlias = tuple[int, int, int, int]
SessionVariableDirectoryIdentity: TypeAlias = tuple[int, int]


class SessionVariableMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    description: str = ""
    min: StrictInt | StrictFloat | None = None
    max: StrictInt | StrictFloat | None = None
    integer: bool = False
    percent: bool = False
    display: Literal["auto", "number", "bar", "gauge"] = "auto"


class SessionVariableIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    kind: Literal["value", "metadata", "constraint", "path"]
    code: str
    message: str
    key: str | None = None


class SessionVariableEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    path: str
    metadata_path: str
    group: str
    kind: Literal["number", "string", "invalid"]
    value: StrictInt | StrictFloat | StrictStr | None
    raw_value: str | None
    raw_metadata: dict[str, str] | None
    metadata: SessionVariableMetadata
    issues: list[SessionVariableIssue] = Field(default_factory=list)


class SessionVariablePoolResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    directory_path: str
    root_exists: bool
    scan_complete: bool
    version: str
    variables: list[SessionVariableEntry] = Field(default_factory=list)
    issues: list[SessionVariableIssue] = Field(default_factory=list)


class SessionVariableSnapshotNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relative_path: str
    is_directory: bool
    content: bytes | None = None
    identity: SessionVariableFileIdentity | None = None
    issues: list[SessionVariableIssue] = Field(default_factory=list)


class SessionVariableSourceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    root_exists: bool
    version: str
    nodes: list[SessionVariableSnapshotNode] = Field(default_factory=list)
    issues: list[SessionVariableIssue] = Field(default_factory=list)
    scan_complete: bool = True


class SessionVariableInheritanceData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources: list[SessionVariableSourceSnapshot]
    target_nodes: list[SessionVariableSnapshotNode]
