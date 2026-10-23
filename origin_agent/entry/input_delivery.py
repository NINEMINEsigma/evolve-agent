"""会话级非持久化输入记录；接收成功先于唤醒，保存成功后才释放。"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from typing import Generic, TypeVar

from pydantic import BaseModel

from entity.constant import InputDeliveryState
from entity.puretype import InputDelivery, QueuedMessage, ShutdownInputReport
from entity.messages import ToolResultMessage
from system.lifecycle import ApplicationStoppingError, LifecycleFailure
from interface.runtime_system import IRuntimeSystem

PayloadT = TypeVar("PayloadT", bound=BaseModel)


class InputDeliveryBuffer(Generic[PayloadT]):
    """唯一记录表；记录对象保留原payload身份，不按文本或id数字去重。"""

    def __init__(self, runtime: IRuntimeSystem) -> None:
        self._runtime = runtime
        self._lock = threading.RLock()
        self._records: dict[int, InputDelivery[PayloadT]] = {}
        self._frozen = False
        self._accepted = 0
        self._appended = 0
        self._persisted = 0
        self._ephemeral = 0

    def accept(
        self,
        payload: PayloadT,
        *,
        ready: bool = True
        ) -> int:
        with self._runtime.admission(), self._lock:
            if self._frozen:
                raise ApplicationStoppingError("Input delivery has been frozen")
            sequence = self._runtime.next_input_sequence()
            self._records[sequence] = InputDelivery(sequence=sequence, payload=payload, ready=ready)
            self._accepted += 1
            return sequence

    def freeze(self) -> None:
        # 与accept使用同一记录锁；不要求Runtime仍在RUNNING。
        with self._lock:
            self._frozen = True

    @property
    def frozen(self) -> bool:
        with self._lock:
            return self._frozen

    def mark_ready(self, sequence: int) -> None:
        with self._lock:
            record = self._records[sequence]
            if record.state is not InputDeliveryState.ACCEPTED:
                raise LifecycleFailure("Only an accepted input can finish preparation")
            record.ready = True

    def reserve_pending(
        self,
        *,
        reservation_id: str,
        isolate: Callable[[PayloadT], bool] | None = None,
        stop_before: Callable[[PayloadT], bool] | None = None,
        ) -> list[InputDelivery[PayloadT]]:
        """先选择再预订；谓词须同步且不修改状态，失败不留下部分预订。"""
        with self._lock:
            if self._frozen:
                return []
            result: list[InputDelivery[PayloadT]] = []
            for record in sorted(self._records.values(), key=lambda item: item.sequence):
                # 未提交的已预订记录同样可以形成屏障，避免工具注入越过等锁输入。
                if (
                    stop_before is not None
                    and record.state in (InputDeliveryState.ACCEPTED, InputDeliveryState.RESERVED)
                    and stop_before(record.payload)
                ):
                    break
                if record.state is not InputDeliveryState.ACCEPTED:
                    continue
                if not record.ready:
                    break
                isolated = isolate is not None and isolate(record.payload)
                if isolated and result:
                    break
                result.append(record)
                if isolated:
                    break
            # 所有谓词完成后才提交，不在状态修改之间调用外部函数。
            for record in result:
                record.state = InputDeliveryState.RESERVED
                record.reservation_id = reservation_id
            return result

    def reserve_shutdown(self, *, reservation_id: str) -> list[InputDelivery[PayloadT]]:
        """仅在全部写入任务结束后调用；包含未ready及已APPENDED未保存记录。"""
        with self._lock:
            if not self._frozen:
                raise LifecycleFailure("Shutdown input collection requires frozen admission")
            result = sorted(self._records.values(), key=lambda item: item.sequence)
            for record in result:
                if record.state is InputDeliveryState.RESERVED:
                    raise LifecycleFailure("Input is still reserved by an active operation")
                if record.state is InputDeliveryState.ACCEPTED:
                    record.state = InputDeliveryState.RESERVED
                    record.reservation_id = reservation_id
            return result

    def mark_appended(
        self,
        sequence: int,
        history_index: int
        ) -> None:
        with self._lock:
            record = self._records[sequence]
            if record.state is not InputDeliveryState.RESERVED or history_index < 0:
                raise LifecycleFailure("Input must be reserved before a valid History append")
            record.state = InputDeliveryState.APPENDED
            record.history_index = history_index
            self._appended += 1

    def mark_persisted(self, sequences: Sequence[int]) -> None:
        with self._lock:
            records = self._validate_appended(sequences)
            for record in records:
                record.state = InputDeliveryState.PERSISTED
                del self._records[record.sequence]
                self._persisted += 1

    def _validate_appended(self, sequences: Sequence[int]) -> list[InputDelivery[PayloadT]]:
        if len(set(sequences)) != len(sequences):
            raise LifecycleFailure("Duplicate input commit confirmation")
        records = [self._records[sequence] for sequence in sequences]
        if any(record.state is not InputDeliveryState.APPENDED for record in records):
            raise LifecycleFailure("Input must be appended before commit confirmation")
        return records

    def release_reservation(self, reservation_id: str) -> None:
        with self._lock:
            for record in self._records.values():
                if record.reservation_id == reservation_id and record.state is InputDeliveryState.RESERVED:
                    record.state = InputDeliveryState.ACCEPTED
                    record.reservation_id = None

    def uncommitted(self) -> list[InputDelivery[PayloadT]]:
        with self._lock:
            return sorted(self._records.values(), key=lambda item: item.sequence)

    def mark_ephemeral(self, sequences: Sequence[int]) -> None:
        with self._lock:
            for record in self._validate_appended(sequences):
                del self._records[record.sequence]
                self._ephemeral += 1

    def accept_shutdown_transfer(
        self,
        sequence: int,
        payload: PayloadT
        ) -> None:
        """只接受已存在的全局sequence；不开放普通接收或重新分配身份。"""
        with self._lock:
            if not self._frozen:
                raise LifecycleFailure("Shutdown transfer requires frozen admission")
            if sequence <= 0 or sequence in self._records:
                raise LifecycleFailure("Invalid or duplicate shutdown input transfer")
            self._records[sequence] = InputDelivery(sequence=sequence, payload=payload)
            self._accepted += 1

    def transfer_to(self, target: InputDeliveryBuffer[PayloadT]) -> None:
        """同一Runtime内转交未提交记录；调用方须先结束源消费者与全部预订。"""
        if target is self:
            return
        if self._runtime is not target._runtime:
            raise LifecycleFailure("Cannot transfer input across runtimes")
        # 按锁对象身份排序仅用于锁顺序，不用整数身份替代消息绑定。
        first, second = (self, target) if id(self) < id(target) else (target, self)
        with first._lock, second._lock:
            if not self._frozen:
                raise LifecycleFailure("Input transfer requires frozen source admission")
            if any(item.state is not InputDeliveryState.ACCEPTED for item in self._records.values()):
                raise LifecycleFailure("Cannot transfer reserved or unconfirmed History input")
            if self._records.keys() & target._records.keys():
                raise LifecycleFailure("Duplicate input sequence during handoff")
            count = len(self._records)
            target._records.update(self._records)
            target._accepted += count
            self._accepted -= count
            self._records.clear()

    def shutdown_report(self) -> ShutdownInputReport:
        with self._lock:
            return ShutdownInputReport(accepted=self._accepted, appended=self._appended,
                                       persisted=self._persisted, ephemeral=self._ephemeral)


class ToolInputReservation:
    """每次工具结果独立预订输入，只认可绑定的真实消息对象。"""

    def __init__(
        self,
        buffer: InputDeliveryBuffer[QueuedMessage],
        reservation_id: str
        ) -> None:
        self._buffer = buffer
        self.reservation_id = reservation_id
        self._items: list[InputDelivery[QueuedMessage]] = []
        self._message: ToolResultMessage | None = None
        self._called = False
        self._released = False

    def __call__(self, result: dict) -> dict | None:
        if self._called or self._released:
            raise LifecycleFailure("Tool input reservation can only be used once")
        self._called = True
        self._items = self._buffer.reserve_pending(
            reservation_id=self.reservation_id,
            stop_before=lambda item: item.require_tool_call,
        )
        if not self._items:
            return None
        existing = result.get("_queued_messages")
        messages = list(existing) if isinstance(existing, list) else []
        for delivery in self._items:
            item = delivery.payload
            messages.append({"role": "user", "character_name": item.character_name,
                             "source": item.source, "timestamp": item.timestamp,
                             "content": item.content,
                             "visible_characters": item.visible_characters,
                             "response_characters": item.response_characters})
        return {"_queued_messages": messages, "consumed_client_message_ids": [
            delivery.payload.client_message_id for delivery in self._items
            if delivery.payload.client_message_id
        ]}

    def bind_result(self, message: ToolResultMessage) -> None:
        if not self._called or self._released or self._message is not None:
            raise LifecycleFailure("Invalid tool result reservation binding")
        self._message = message

    def mark_appended(
        self,
        message: ToolResultMessage,
        history_index: int
        ) -> None:
        if self._released or self._message is not message:
            raise LifecycleFailure("Tool input commit does not match the bound message")
        for delivery in self._items:
            self._buffer.mark_appended(delivery.sequence, history_index)

    def mark_persisted(self) -> None:
        self._buffer.mark_persisted([item.sequence for item in self._items])
        self._released = True

    def abort(self) -> None:
        # 已APPENDED记录不退回重放，保存失败由Loop保留并传播。
        self._buffer.release_reservation(self.reservation_id)
        self._released = True
