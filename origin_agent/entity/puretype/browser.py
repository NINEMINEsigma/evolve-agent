"""Browser cleanup result types. These snapshots are not independently persisted."""

from pydantic import BaseModel

from .resource_cleanup import CleanupReport


class HeadlessCleanupResult(BaseModel):
    """Count only owned headless processes confirmed exited in this snapshot."""

    killed: int
    cleanup: CleanupReport
