"""External resource cleanup reports. These process snapshots are not persisted."""

from pydantic import BaseModel, Field


class CleanupWarning(BaseModel):
    """One observed cleanup deadline without a confirmed resource release."""

    owner: str
    resource_id: str
    phase: str
    timeout_seconds: float
    message: str


class CleanupReport(BaseModel):
    """Completion is true only when every targeted resource is confirmed released."""

    complete: bool
    pending_resources: list[str] = Field(default_factory=list)
    warnings: list[CleanupWarning] = Field(default_factory=list)
