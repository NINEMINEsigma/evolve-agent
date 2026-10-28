"""One subprocess generation and its real consumer/cleanup handoffs."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
import subprocess
import threading
from typing import Any

from entity.constant import SubprocessCreationState
from system.lifecycle_errors import LifecycleFailure
from system.process_termination import OwnedProcessIdentity
from system.resource_cleanup import CleanupReservation, ResourceCleanupHandle


class SubprocessOperation:
    """Runtime ownership, never a serializable data model.

    Runner index facts use the Runner lock. This lock protects only local
    transitions; futures notify their callbacks after releasing it.
    """

    def __init__(self, *, session_id: str, reservation: CleanupReservation) -> None:
        self.session_id = session_id
        self.reservation = reservation
        self.process: subprocess.Popen[bytes] | asyncio.subprocess.Process | None = None
        self.identity: OwnedProcessIdentity | None = None
        self.io_finished: Future[None] = Future()
        self.cleanup_submission: Future[ResourceCleanupHandle] | None = None
        self.cleanup_handle: ResourceCleanupHandle | None = None
        self.resources_closed = threading.Event()
        self.body_finished = False
        self.creation_error: BaseException | None = None
        self.io_tasks: tuple[asyncio.Task[Any], ...] = ()
        self.io_join_task: asyncio.Task[None] | None = None
        self.native_cleanup_task: asyncio.Task[None] | None = None
        self.spawn_task: asyncio.Task[asyncio.subprocess.Process] | None = None
        self._state = SubprocessCreationState.CREATING
        self._abandoned = False
        self._lock = threading.RLock()
        self._identity_bound = False
        self._io_completion_claimed = False
        self._uncreated_release_claimed = False

    @property
    def state(self) -> SubprocessCreationState:
        with self._lock:
            return self._state

    @property
    def abandoned(self) -> bool:
        with self._lock:
            return self._abandoned

    def bind_process(self, process: subprocess.Popen[bytes] | asyncio.subprocess.Process) -> None:
        with self._lock:
            if self.process is not None or self._state is SubprocessCreationState.FAILED:
                raise LifecycleFailure("Subprocess operation already has a creation result")
            self.process = process
            if self._state is SubprocessCreationState.CREATING:
                self._state = SubprocessCreationState.READY

    def bind_identity(self, identity: OwnedProcessIdentity | None) -> None:
        with self._lock:
            if self.process is None or self._identity_bound:
                raise LifecycleFailure("Subprocess identity cannot be bound in this state")
            self.identity = identity
            self._identity_bound = True

    def claim_consumer(self) -> bool:
        with self._lock:
            if self._state is SubprocessCreationState.ABANDONED:
                return False
            if self._state is not SubprocessCreationState.READY:
                raise LifecycleFailure("Subprocess creation result cannot be claimed twice")
            self._state = SubprocessCreationState.CLAIMED
            return True

    def abandon_consumer(self) -> bool:
        with self._lock:
            if self._state is not SubprocessCreationState.CLAIMED:
                # FAILED结果尚未被等待方取得时，也必须记录后到的取消。
                self._abandoned = True
            if self._state in (SubprocessCreationState.CREATING, SubprocessCreationState.READY):
                self._state = SubprocessCreationState.ABANDONED
            return self.process is not None and self._abandoned

    def fail_creation(self, error: BaseException) -> None:
        with self._lock:
            if self.process is not None:
                raise LifecycleFailure("A bound subprocess is not an uncreated operation")
            self.creation_error = error
            # 保留等待方放弃事实，迟到错误仍须由创建完成回调观察。
            if self._state is not SubprocessCreationState.ABANDONED:
                self._state = SubprocessCreationState.FAILED

    def claim_uncreated_release(self) -> bool:
        with self._lock:
            if self.process is not None:
                raise LifecycleFailure("Cannot return a reservation for a created subprocess")
            if self._uncreated_release_claimed:
                return False
            self._uncreated_release_claimed = True
            return True

    def mark_io_finished(self) -> None:
        with self._lock:
            if self._io_completion_claimed:
                return
            self._io_completion_claimed = True
        self.io_finished.set_result(None)

    def mark_body_finished(self) -> None:
        with self._lock:
            self.body_finished = True

    def mark_abandoned(self) -> None:
        self.abandon_consumer()

    def claim_cleanup_submission(self) -> tuple[Future[ResourceCleanupHandle], bool]:
        with self._lock:
            if self.cleanup_submission is not None:
                return self.cleanup_submission, False
            self.cleanup_submission = Future()
            return self.cleanup_submission, True

    def attach_cleanup_handle(self, handle: ResourceCleanupHandle) -> None:
        with self._lock:
            if self.cleanup_handle is not None and self.cleanup_handle is not handle:
                raise LifecycleFailure("Subprocess operation has a different cleanup handle")
            self.cleanup_handle = handle

    def mark_resources_closed(self) -> None:
        self.resources_closed.set()

    def is_released(self) -> bool:
        return self.resources_closed.is_set()
