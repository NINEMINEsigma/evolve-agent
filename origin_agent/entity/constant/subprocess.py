"""子进程创建与业务消费者交接状态；仅用于进程内生命周期。"""

from enum import Enum


class SubprocessCreationState(str, Enum):
    """真实创建结果只能交给业务消费者或清理所有者一次。"""

    CREATING = "creating"
    READY = "ready"
    CLAIMED = "claimed"
    ABANDONED = "abandoned"
    FAILED = "failed"
