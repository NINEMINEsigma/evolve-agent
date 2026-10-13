"""仅供进程内生命周期协调使用的数据；不加入持久化 History 格式。"""

import asyncio
import concurrent.futures
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from entity.constant.application import InputDeliveryState, TaskOwnership
from .approval import ToolCallMeta

PayloadT = TypeVar("PayloadT", bound=BaseModel)


class ManagedTaskRecord(BaseModel):
    """TaskOwner 的进程内所有权记录，不参与任何持久化。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    task: asyncio.Task[Any]
    ownership: TaskOwnership
    waiter: asyncio.Task[Any] | None = None
    cancel_timeout: float = Field(gt=0)
    expected_cancel: bool = False
    request_released: bool = False
    result_delivered: bool = False
    cleanup_task: asyncio.Task[None] | None = None
    cancel_deadline: float | None = None
    terminal_error: BaseException | None = None
    terminal_reported: bool = False
    expected_failure: bool = False
    timeout_error: BaseException | None = None


class SyncToolCallRecord(BaseModel):
    """真实同步工具 Future 与结果交接；取消等待不代表线程已经退出。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    future: concurrent.futures.Future[Any]
    request_released: bool = False
    cancelled_while_running: bool = False
    failure_reported: bool = False


class InputDelivery(BaseModel, Generic[PayloadT]):
    """一条已接受输入的准备与提交记录，payload 保留原始模型。"""

    sequence: int = Field(gt=0)
    payload: PayloadT
    state: InputDeliveryState = InputDeliveryState.ACCEPTED
    history_index: int | None = None
    reservation_id: str | None = None
    ready: bool = True


class ShutdownInputReport(BaseModel):
    """只落历史关闭的输入处理计数，不把内存提交伪标为已保存。"""

    accepted: int = Field(default=0, ge=0)
    appended: int = Field(default=0, ge=0)
    persisted: int = Field(default=0, ge=0)
    ephemeral: int = Field(default=0, ge=0)


class ToolResultNotification(BaseModel):
    """工具结果提交后的发送数据，与持久化工具消息分离。"""

    tool_name: str
    session_id: str
    tool_call_id: str
    character_name: str
    display_content: str
    tool_call_meta: ToolCallMeta
    embedded_messages: list[dict[str, Any]] | None = None
    consumed_client_message_ids: list[str] | None = None
    ui_result: dict[str, Any] = Field(default_factory=dict)
