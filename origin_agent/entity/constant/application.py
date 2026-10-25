"""应用生命周期、输入投递状态与进程退出约定。"""

from enum import Enum


class ApplicationState(str, Enum):
    """进程生命周期；STOPPING 后不再接受新的业务工作。"""

    NEW = "new"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    CLOSED = "closed"
    FAILED = "failed"


class ShutdownReason(str, Enum):
    """关闭原因；失败优先于任何正常结束或进化请求。"""

    NORMAL = "normal"
    EVOLUTION = "evolution"
    FAILURE = "failure"


class TaskOwnership(str, Enum):
    """任务结果的处理责任；不是任务所在的线程或事件循环。"""

    BACKGROUND = "background"
    REQUEST = "request"


class InputDeliveryState(str, Enum):
    """输入提交状态；只有实际保存成功才能进入 PERSISTED。"""

    ACCEPTED = "accepted"
    RESERVED = "reserved"
    APPENDED = "appended"
    PERSISTED = "persisted"


# 进程退出码；与根目录 run.py 的既有停止、进化、回退协议一致。
EXIT_NORMAL: int = 0
EXIT_EVOLVED: int = -1
EXIT_FAILURE: int = 1

# 应用关闭硬截止（秒）；超过后强制失败退出，绝不报告进化成功。
APPLICATION_SHUTDOWN_TIMEOUT_SECONDS: float = 5
# 单个系统停止活动任务的等待上限（秒），不作为继续生成回复的宽限期。
SYSTEM_QUIESCE_TIMEOUT_SECONDS: float = 10.0
# 关闭期间单次前端发送的等待上限（秒），写盘不依赖前端确认。
SHUTDOWN_SEND_TIMEOUT_SECONDS: float = 1.0
# Gateway 完成实际启动的等待上限（秒）。
GATEWAY_START_TIMEOUT_SECONDS: float = 30.0
