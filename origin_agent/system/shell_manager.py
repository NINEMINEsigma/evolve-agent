"""Windows ConPTY Shell会话的进程级生命周期管理。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import subprocess  # nosec
import sys
import threading
import time
import uuid
from functools import wraps
from types import CoroutineType
from typing import Any, Callable, Concatenate, ParamSpec, TypeVar

from entity.constant import (
    ApplicationState,
    SHELL_DEFAULT_COLS,
    SHELL_DEFAULT_ROWS,
    SHELL_DEFAULT_TYPE,
    SHELL_ID_LENGTH,
    SHELL_OUTPUT_QUIET_SECONDS,
    SHELL_STARTUP_SETTLE_SECONDS,
    SHELL_RAW_BUFFER_MAX_CHARS,
    SHELL_READ_MAX_CHARS,
    SHELL_STOP_WAIT_SECONDS,
    SHELL_SUPPORTED_TYPES,
    SHELL_TEXT_BUFFER_MAX_CHARS,
    SHELL_WAIT_TIMEOUT_SECONDS,
    SYSTEM_QUIESCE_TIMEOUT_SECONDS,
)
from entity.puretype import ShellInfo, ShellOutputSlice
from entity.puretype.resource_cleanup import CleanupReport
from entity.puretype.shell import ShellStopResult
from framework import AsyncSystem
from system.lifecycle import ApplicationStoppingError, LifecycleFailure
from system.process_termination import OwnedProcessIdentity
from system.resource_cleanup import CleanupProducer, ResourceCleanupHandle
from interface.runtime_system import IRuntimeSystem
from interface.sandbox import ISandbox
from interface.shell_manager import IShellManager
from system.sandbox import SandboxError
from system.shell_text import ShellTextNormalizer

logger = logging.getLogger(__name__)


class ShellError(RuntimeError):
    """Shell会话操作失败。"""


class ShellAccessError(ShellError):
    """Shell会话不存在或调用者无权访问。"""


class _ShellSession:
    """单个 ConPTY Shell 的不可序列化运行时状态。"""

    def __init__(
        self,
        *,
        shell_id: str,
        pty: Any,
        pid: int | None,
        session_id: str,
        character_name: str,
        shell_type: str,
        cwd: str,
        event_loop: asyncio.AbstractEventLoop
        ) -> None:
        now = time.time()
        self.shell_id = shell_id
        self.pty = pty
        self.pid = pid
        self.session_id = session_id
        self.character_name = character_name
        self.shell_type = shell_type
        self.cwd = cwd
        self.started_at = now
        self.last_activity_at = now
        self.running = True
        self.exit_code: int | None = None
        self.termination: str | None = None
        self.error: str | None = None

        self.lock = threading.RLock()
        # PTY control calls are serialized separately from text-state access.
        # The reader must not hold this lock while blocked in pty.read().
        self.native_lock = threading.RLock()
        self.reader_exited = threading.Event()
        self.native_closed = threading.Event()
        self.operation_lock = asyncio.Lock()
        self.output_event = asyncio.Event()
        self.closing = threading.Event()
        self.event_loop = event_loop
        self.reader_thread: threading.Thread | None = None
        self.normalizer = ShellTextNormalizer()
        self.raw_text = ""
        self.text = ""
        self.base_offset = 0
        self.total_chars = 0
        self.last_output_monotonic = time.monotonic()
        self.version = 0
        self.process_identity: OwnedProcessIdentity | None = None
        self.cleanup_handle: ResourceCleanupHandle | None = None

    def signal_output(self) -> None:
        try:
            self.event_loop.call_soon_threadsafe(self.output_event.set)
        except RuntimeError:
            pass

    def exit_status(self) -> int | None:
        with self.native_lock:
            if self.native_closed.is_set():
                return None
            try:
                return self.pty.exitstatus
            except Exception:
                return None

    def append_raw(self, raw: str) -> None:
        if not raw:
            return
        with self.lock:
            self.raw_text = (self.raw_text + raw)[-SHELL_RAW_BUFFER_MAX_CHARS:]
            normalized = self.normalizer.feed(raw)
            # 每个原始输出块都代表终端活动；即使可见逻辑行尚未提交，
            # 也必须唤醒等待协程并重新计算静默窗口。
            self.last_output_monotonic = time.monotonic()
            self.last_activity_at = time.time()
            self.version += 1
            if normalized:
                self._append_text_locked(normalized)
        self.signal_output()

    def flush_pending(self) -> bool:
        with self.lock:
            normalized = self.normalizer.flush_pending()
            if not normalized:
                return False
            self._append_text_locked(normalized)
        self.signal_output()
        return True

    def finish_output(self) -> None:
        with self.lock:
            normalized = self.normalizer.finish()
            if normalized:
                self._append_text_locked(normalized)
        self.signal_output()

    def _append_text_locked(self, text: str) -> None:
        self.text += text
        self.total_chars += len(text)
        if len(self.text) > SHELL_TEXT_BUFFER_MAX_CHARS:
            dropped = len(self.text) - SHELL_TEXT_BUFFER_MAX_CHARS
            self.text = self.text[dropped:]
            self.base_offset += dropped
        self.last_output_monotonic = time.monotonic()
        self.last_activity_at = time.time()
        self.version += 1

    def mark_exited(
        self,
        error: str | None = None,
        termination: str | None = None
        ) -> None:
        exit_code = self.exit_status()
        with self.lock:
            self.running = False
            self.error = error
            if self.termination is None and termination is not None:
                self.termination = termination
            if exit_code is not None or self.exit_code is None:
                self.exit_code = exit_code
            self.last_activity_at = time.time()
            self.version += 1
        self.signal_output()

    def touch(self) -> None:
        with self.lock:
            self.last_activity_at = time.time()

    def info(self) -> ShellInfo:
        with self.lock:
            return ShellInfo(
                shell_id=self.shell_id,
                pid=self.pid,
                session_id=self.session_id,
                character_name=self.character_name,
                shell_type=self.shell_type,
                cwd=self.cwd,
                started_at=self.started_at,
                last_activity_at=self.last_activity_at,
                running=self.running,
                exit_code=self.exit_code,
                termination=self.termination,
                cleanup=self.cleanup_handle.snapshot() if self.cleanup_handle is not None else None,
            )

    def output_slice(
        self,
        offset: int,
        limit: int,
        wait_reason: str
        ) -> ShellOutputSlice:
        with self.lock:
            if offset > self.total_chars:
                raise ShellError(
                    f"offset {offset} exceeds total_chars {self.total_chars}"
                )
            truncated = offset < self.base_offset
            effective_offset = max(offset, self.base_offset)
            start = effective_offset - self.base_offset
            content = self.text[start:start + limit]
            next_offset = effective_offset + len(content)
            return ShellOutputSlice(
                shell_id=self.shell_id,
                content=content,
                offset=effective_offset,
                next_offset=next_offset,
                base_offset=self.base_offset,
                total_chars=self.total_chars,
                remaining_chars=max(0, self.total_chars - next_offset),
                truncated=truncated,
                running=self.running,
                exit_code=self.exit_code,
                wait_reason=wait_reason,
            )


ShellParams = ParamSpec("ShellParams")
ShellResult = TypeVar("ShellResult")


def _tracked_operation(
    method: Callable[
        Concatenate[ShellManager, ShellParams],
        CoroutineType[Any, Any, ShellResult],
    ],
) -> Callable[
    Concatenate[ShellManager, ShellParams],
    CoroutineType[Any, Any, ShellResult],
]:
    """登记整个业务操作，关闭时同时覆盖锁等待和原生调用等待。"""
    @wraps(method)
    async def invoke(
        self: ShellManager,
        *args: ShellParams.args,
        **kwargs: ShellParams.kwargs
        ) -> ShellResult:
        task = asyncio.current_task()
        if task is None:
            raise LifecycleFailure("Shell operation requires an asyncio task")
        with self.runtime.admission():
            with self._registry_lock:
                if self._admission_closed:
                    raise ApplicationStoppingError("Shell admission has been closed")
                self._operations.add(task)
        try:
            return await method(self, *args, **kwargs)
        finally:
            self._operations.discard(task)
    return invoke  # type: ignore[return-value]


class ShellManager(IShellManager):
    """Application 持有的唯一 Shell会话管理器。

    注册为 framework AsyncSystem，依赖 RuntimeSystem 与 Sandbox；由 Application
    在 P22 装配后经 ``app.get_system(IShellManager)`` 取得。virtual_awake 只取得
    Sandbox 依赖，不强制创建 Shell 或导入不可用平台的 PTY。关闭接收后不再允
    许新建 Shell 会话；应用关闭时停止每个 Shell，尽力回收 reader 和 PTY，
    资源释放失败作为 Shell 操作/清理错误返回或记录，不升级为进程级失败。
    """

    def __init__(self) -> None:
        super().__init__(dependencies=(IRuntimeSystem, ISandbox))
        self._sandbox: ISandbox | None = None
        self._runtime: IRuntimeSystem | None = None
        self._conpty_spawn_lock = threading.Lock()
        self._operations: set[asyncio.Task[Any]] = set()
        self._native_tasks: set[asyncio.Task[Any]] = set()
        self._stop_tasks: dict[str, asyncio.Task[None]] = {}
        self._cleanup_failures: list[BaseException] = []
        self._shells: dict[str, _ShellSession] = {}
        self._session_aliases: dict[str, str] = {}
        self._registry_lock = threading.RLock()
        self._admission_closed = False
        self._cleanup_producer: CleanupProducer | None = None

    async def virtual_awake(self) -> None:
        self._runtime = self.get_system(IRuntimeSystem)
        self._sandbox = self.get_system(ISandbox)
        self._cleanup_producer = self.runtime.cleanup.open_producer(
            owner="ShellManager",
            loop=asyncio.get_running_loop(),
        )

    @property
    def runtime(self) -> IRuntimeSystem:
        if self._runtime is None:
            raise LifecycleFailure("ShellManager has not been awakened")
        return self._runtime

    async def _native_call(
        self,
        fn: Callable[..., ShellResult],
        *args: Any,
        report_failure: bool = True
        ) -> ShellResult:
        task = asyncio.create_task(asyncio.to_thread(fn, *args), name="shell-native-call")
        self._native_tasks.add(task)
        try:
            return await asyncio.shield(task)
        finally:
            if task.done():
                self._native_tasks.discard(task)
            else:
                task.add_done_callback(
                    lambda done: self._native_finished(done, report_failure=report_failure)
                )

    def _native_finished(
        self,
        task: asyncio.Task[Any],
        *,
        report_failure: bool = True
        ) -> None:
        self._native_tasks.discard(task)
        if task.cancelled():
            if report_failure:
                self.runtime.record_failure(LifecycleFailure("Shell native operation was cancelled"))
            return
        error = task.exception()
        if report_failure and error is not None and not isinstance(error, (EOFError, ApplicationStoppingError)):
            self.runtime.record_failure(error)

    @property
    def sandbox(self) -> ISandbox:
        if self._sandbox is None:
            raise LifecycleFailure("ShellManager has not been awakened")
        return self._sandbox

    def close_admission(self) -> None:
        """关闭后不再允许新建 Shell 会话；已持有 Shell 仍可自然结束或被停止。"""
        with self._registry_lock:
            self._admission_closed = True

    @staticmethod
    def is_available() -> bool:
        if sys.platform != "win32":
            return False
        try:
            from winpty import PtyProcess
            from winpty.enums import Backend
            return PtyProcess is not None and Backend is not None
        except Exception:
            return False

    @_tracked_operation
    async def start_shell(
        self,
        owner_session_id: str,
        character_name: str,
        shell_type: str,
        cwd: str,
        command: str
        ) -> tuple[ShellInfo, ShellOutputSlice, dict[str, str]]:
        with self._registry_lock:
            if self._admission_closed:
                raise ShellError("Shell admission has been closed")
        self._validate_owner(owner_session_id, character_name)
        shell_type = shell_type.strip().lower() or SHELL_DEFAULT_TYPE
        if shell_type not in SHELL_SUPPORTED_TYPES:
            raise ShellError(
                f"Unsupported shell type: {shell_type}. "
                f"Supported: {sorted(SHELL_SUPPORTED_TYPES)}"
            )
        self._validate_line(command, allow_empty=False, field="command")
        if not self.is_available():
            raise ShellError(
                "Windows ConPTY support is unavailable; install pywinpty>=3.0.5,<4"
            )

        try:
            resolved = self.sandbox.resolve_read(cwd)
        except SandboxError as exc:
            raise ShellError(f"cwd resolution failed: {exc}") from exc
        if not resolved.real.is_dir():
            raise ShellError(f"cwd does not exist or is not a directory: {cwd}")

        executable, arguments = self._resolve_shell(shell_type)
        environment, references = self._build_environment(shell_type)
        owner_session_id = self._canonical_owner_session(owner_session_id)
        shell_id = uuid.uuid4().hex[:SHELL_ID_LENGTH]
        event_loop = asyncio.get_running_loop()

        def _spawn() -> Any:
            from winpty import PtyProcess
            from winpty.enums import Backend

            # pywinpty 3.0.5 treats backend=0 as false in PtyProcess.spawn().
            # Protect the process-wide environment change with a short lock.
            with self._conpty_spawn_lock:
                previous_backend = os.environ.get("PYWINPTY_BACKEND")
                os.environ["PYWINPTY_BACKEND"] = str(Backend.ConPTY)
                try:
                    return PtyProcess.spawn(
                        [executable, *arguments],
                        cwd=str(resolved.real),
                        env=environment,
                        dimensions=(SHELL_DEFAULT_ROWS, SHELL_DEFAULT_COLS),
                        backend=Backend.ConPTY,
                    )
                finally:
                    if previous_backend is None:
                        os.environ.pop("PYWINPTY_BACKEND", None)
                    else:
                        os.environ["PYWINPTY_BACKEND"] = previous_backend

        abandoned = False

        async def create_state() -> _ShellSession:
            pty = await asyncio.to_thread(_spawn)
            state = _ShellSession(
                shell_id=shell_id,
                pty=pty,
                pid=pty.pid,
                session_id=owner_session_id,
                character_name=character_name,
                shell_type=shell_type,
                cwd=cwd,
                event_loop=event_loop,
            )
            with self._registry_lock:
                self._shells[shell_id] = state
                closing = self._admission_closed
            try:
                if abandoned or closing or self.runtime.state != ApplicationState.RUNNING:
                    raise ApplicationStoppingError("Shell created after its operation stopped")
                state.reader_thread = threading.Thread(
                    target=self._reader_loop,
                    args=(state,),
                    daemon=True,
                    name=f"shell-reader-{shell_id}",
                )
                state.reader_thread.start()
                return state
            except BaseException:
                await self._remove_and_stop(state)
                raise

        startup = asyncio.create_task(create_state(), name=f"shell-create-{shell_id}")
        self._native_tasks.add(startup)
        try:
            state = await asyncio.shield(startup)
        except asyncio.CancelledError:
            abandoned = True
            if startup.done() and not startup.cancelled() and startup.exception() is None:
                await self._remove_and_stop(startup.result())
            raise
        finally:
            if startup.done():
                self._native_tasks.discard(startup)
            else:
                startup.add_done_callback(self._native_finished)

        try:
            await self._wait_for_startup_quiet(state)
            async with state.operation_lock:
                # 初始化提示符属于 Shell 建立阶段，不混入首条命令结果。
                state.flush_pending()
                start_offset = self._total_chars(state)
                await self._write_line(state, command)
                output = await self._wait_for_output(
                    state,
                    start_offset,
                    SHELL_READ_MAX_CHARS,
                    SHELL_WAIT_TIMEOUT_SECONDS,
                    wait_for_quiet=True,
                )
            return state.info(), output, references
        except BaseException:
            await self._remove_and_stop(state)
            raise

    @_tracked_operation
    async def read_shell(
        self,
        owner_session_id: str,
        character_name: str,
        shell_id: str,
        offset: int,
        limit: int,
        wait_timeout: float
        ) -> ShellOutputSlice:
        if offset < 0:
            raise ShellError("offset must be >= 0")
        if not 1 <= limit <= SHELL_READ_MAX_CHARS:
            raise ShellError(f"limit must be between 1 and {SHELL_READ_MAX_CHARS}")
        if not 0 <= wait_timeout <= SHELL_WAIT_TIMEOUT_SECONDS:
            raise ShellError(
                f"timeout must be between 0 and {SHELL_WAIT_TIMEOUT_SECONDS:g}"
            )
        state = self._get_owned(owner_session_id, character_name, shell_id)
        with state.lock:
            if offset > state.total_chars:
                raise ShellError(
                    f"offset {offset} exceeds total_chars {state.total_chars}"
                )
        async with state.operation_lock:
            state.touch()
            if offset < self._total_chars(state) or wait_timeout == 0:
                return state.output_slice(offset, limit, "available")
            return await self._wait_for_output(
                state,
                offset,
                limit,
                wait_timeout,
                wait_for_quiet=True,
            )

    @_tracked_operation
    async def write_shell(
        self,
        owner_session_id: str,
        character_name: str,
        shell_id: str,
        text: str
        ) -> ShellOutputSlice:
        self._validate_line(text, allow_empty=True, field="text")
        state = self._get_owned(owner_session_id, character_name, shell_id)
        async with state.operation_lock:
            self._require_running(state)
            start_offset = self._total_chars(state)
            await self._write_line(state, text)
            return await self._wait_for_output(
                state,
                start_offset,
                SHELL_READ_MAX_CHARS,
                SHELL_WAIT_TIMEOUT_SECONDS,
                wait_for_quiet=True,
            )

    @_tracked_operation
    async def interrupt_shell(
        self,
        owner_session_id: str,
        character_name: str,
        shell_id: str
        ) -> ShellOutputSlice:
        state = self._get_owned(owner_session_id, character_name, shell_id)
        async with state.operation_lock:
            self._require_running(state)
            start_offset = self._total_chars(state)
            try:
                await self._native_call(self._send_interrupt_blocking, state)
            except EOFError as exc:
                raise ShellError(f"Shell is closed: {state.shell_id}") from exc
            state.touch()
            return await self._wait_for_output(
                state,
                start_offset,
                SHELL_READ_MAX_CHARS,
                SHELL_WAIT_TIMEOUT_SECONDS,
                wait_for_quiet=True,
            )

    @_tracked_operation
    async def stop_shell(
        self,
        owner_session_id: str,
        character_name: str,
        shell_id: str
        ) -> ShellStopResult:
        state = self._get_owned(owner_session_id, character_name, shell_id)
        report = await self._remove_and_stop(state)
        info = state.info()
        return ShellStopResult(stopped=report.complete, shell=info, cleanup=report)

    def list_shells(self, session_id: str) -> list[ShellInfo]:
        with self._registry_lock:
            states = [
                state for state in self._shells.values()
                if state.session_id == session_id
            ]
        return sorted(
            (state.info() for state in states),
            key=lambda item: item.started_at,
        )

    @_tracked_operation
    async def stop_shell_for_user(
        self,
        session_id: str,
        shell_id: str
        ) -> ShellStopResult:
        with self._registry_lock:
            state = self._shells.get(shell_id)
            if state is None or state.session_id != session_id:
                raise ShellAccessError("Shell not found")
        report = await self._remove_and_stop(state)
        return ShellStopResult(stopped=report.complete, shell=state.info(), cleanup=report)

    def migrate_session(
        self,
        old_session_id: str,
        new_session_id: str
        ) -> int:
        if not old_session_id or not new_session_id:
            raise ShellError("old and new session IDs are required")
        if old_session_id == new_session_id:
            return 0
        with self._registry_lock:
            target = self._canonical_owner_session_unlocked(new_session_id)
            source = self._canonical_owner_session_unlocked(old_session_id)
            if source == target:
                return 0
            count = 0
            for state in self._shells.values():
                if state.session_id == source:
                    with state.lock:
                        state.session_id = target
                        state.last_activity_at = time.time()
                    count += 1
            self._session_aliases[old_session_id] = target
            for alias, current in list(self._session_aliases.items()):
                if current == source:
                    self._session_aliases[alias] = target
            return count

    async def stop_session(self, session_id: str) -> int:
        with self._registry_lock:
            states = [
                state for state in self._shells.values()
                if state.session_id == session_id
            ]
            self._session_aliases.pop(session_id, None)
        stopped = 0
        for state in states:
            try:
                report = await self._remove_and_stop(state)
                if report.complete:
                    stopped += 1
            except Exception:
                logger.warning(
                    "Failed to stop Shell during session cleanup | shell=%s session=%s",
                    state.shell_id,
                    session_id,
                    exc_info=True,
                )
        return stopped

    async def stop_operations(self) -> None:
        """关闭业务接收，等待实际操作退出后释放所有 PTY。"""
        self.close_admission()
        with self._registry_lock:
            states = tuple(self._shells.values())
            self._session_aliases.clear()
        for state in states:
            state.closing.set()
            state.signal_output()
        current = asyncio.current_task()
        operations = tuple(self._operations)
        if current in operations:
            raise LifecycleFailure("Shell shutdown cannot wait for its own operation")
        for task in operations:
            task.cancel()
        failures: list[BaseException] = []
        if operations:
            done, pending = await asyncio.wait(operations, timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS)
            for task in done:
                if not task.cancelled():
                    error = task.exception()
                    if error is not None:
                        failures.append(error)
            if pending:
                failure = LifecycleFailure("Shell operations have not finished")
                self.runtime.record_failure(failure)
                raise BaseExceptionGroup("Shell shutdown failed", [*failures, failure])

        native_tasks = tuple(self._native_tasks)
        if native_tasks:
            done, pending = await asyncio.wait(native_tasks, timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS)
            for task in done:
                if not task.cancelled():
                    error = task.exception()
                    if error is not None and not isinstance(error, (EOFError, ApplicationStoppingError)):
                        failures.append(error)
            if pending:
                failure = LifecycleFailure("Shell native operations have not finished")
                self.runtime.record_failure(failure)
                raise BaseExceptionGroup("Shell shutdown failed", [*failures, failure])

        # 包含关闭请求时仍在创建、但现在已经完成登记的 Shell。
        with self._registry_lock:
            states = tuple(self._shells.values())
        for state in states:
            try:
                await self._remove_and_stop(state)
            except BaseException:
                # Shell 资源释放属于可选会话资源；失败记录诊断，但不能把
                # 应用已经开始的关闭升级为进程失败。
                logger.warning(
                    "Failed to stop Shell during application cleanup | shell=%s",
                    state.shell_id,
                    exc_info=True,
                )
        for error in self._cleanup_failures:
            logger.warning(
                "Shell cleanup failure was contained | error=%s",
                error,
                exc_info=(type(error), error, error.__traceback__),
            )
        if failures:
            raise BaseExceptionGroup("ShellManager shutdown failed", failures)

    async def virtual_shotdown(self) -> None:
        """关闭：禁止新 Shell，等待操作退出并尽力释放全部 PTY。"""
        await self.stop_operations()

    def _reader_loop(self, state: _ShellSession) -> None:
        error: str | None = None
        try:
            while not state.closing.is_set():
                try:
                    raw = state.pty.read()
                except EOFError:
                    break
                except Exception as exc:
                    if not self._pty_is_alive(state):
                        break
                    error = str(exc)
                    break
                if raw:
                    error = None
                    state.append_raw(raw)
        finally:
            try:
                state.finish_output()
                state.mark_exited(error, "error" if error else "natural")
            finally:
                state.reader_exited.set()
                state.signal_output()

    async def _wait_for_startup_quiet(self, state: _ShellSession) -> None:
        """等待当前新 PTY 的初始化输出稳定，再允许写入首条命令。"""
        deadline = time.monotonic() + SHELL_STARTUP_SETTLE_SECONDS
        saw_output = False
        while time.monotonic() < deadline:
            with state.lock:
                version = state.version
                last_output = state.last_output_monotonic
                running = state.running
            if not running:
                return
            now = time.monotonic()
            if version:
                saw_output = True
            if saw_output and now - last_output >= SHELL_OUTPUT_QUIET_SECONDS:
                return
            remaining = deadline - now
            if saw_output:
                remaining = min(
                    remaining,
                    max(0.0, SHELL_OUTPUT_QUIET_SECONDS - (now - last_output)),
                )
            state.output_event.clear()
            with state.lock:
                if state.version != version:
                    continue
            try:
                await asyncio.wait_for(state.output_event.wait(), remaining)
            except asyncio.TimeoutError:
                return

    async def _wait_for_output(
        self,
        state: _ShellSession,
        offset: int,
        limit: int,
        timeout: float,
        *,
        wait_for_quiet: bool
        ) -> ShellOutputSlice:
        hard_deadline = time.monotonic() + timeout
        while True:
            with state.lock:
                total = state.total_chars
                has_pending = state.normalizer.has_pending_output
                running = state.running
                closing = state.closing.is_set()
                last_output = state.last_output_monotonic
                version = state.version

            if closing:
                return state.output_slice(offset, limit, "stopped")
            if not running:
                state.flush_pending()
                return state.output_slice(offset, limit, "exited")

            has_output = total > offset
            if has_output and not wait_for_quiet:
                return state.output_slice(offset, limit, "available")
            now = time.monotonic()
            has_activity = has_output or has_pending
            if has_activity and now - last_output >= SHELL_OUTPUT_QUIET_SECONDS:
                committed = state.flush_pending() if has_pending else False
                if has_output or committed:
                    return state.output_slice(offset, limit, "quiet")
                # 仅有待处理 CR 或控制状态但没有可见文本，继续等待。
                continue
            if now >= hard_deadline:
                state.flush_pending()
                return state.output_slice(offset, limit, "timeout")

            remaining = hard_deadline - now
            if has_activity:
                remaining = min(
                    remaining,
                    max(0.0, SHELL_OUTPUT_QUIET_SECONDS - (now - last_output)),
                )
            state.output_event.clear()
            with state.lock:
                if state.version != version:
                    continue
            try:
                await asyncio.wait_for(state.output_event.wait(), remaining)
            except asyncio.TimeoutError:
                continue

    async def _write_line(
        self,
        state: _ShellSession,
        text: str
        ) -> None:
        self._require_running(state)
        try:
            await self._native_call(self._write_line_blocking, state, text)
        except EOFError as exc:
            raise ShellError(f"Shell is closed: {state.shell_id}") from exc
        state.touch()

    @staticmethod
    def _write_line_blocking(state: _ShellSession, text: str) -> None:
        with state.native_lock:
            if state.closing.is_set() or state.native_closed.is_set():
                raise EOFError
            state.pty.write(text + "\r")

    @staticmethod
    def _send_interrupt_blocking(state: _ShellSession) -> None:
        with state.native_lock:
            if state.closing.is_set() or state.native_closed.is_set():
                raise EOFError
            state.pty.sendintr()

    async def _remove_and_stop(self, state: _ShellSession) -> CleanupReport:
        state.closing.set()
        state.signal_output()
        if state.cleanup_handle is not None:
            state.cleanup_handle.refresh_completion()
            return await state.cleanup_handle.wait(timeout=SHELL_STOP_WAIT_SECONDS)
        producer = self._cleanup_producer
        if producer is None:
            raise LifecycleFailure("Shell cleanup producer has not been opened")
        reservation = producer.reserve()
        identity = OwnedProcessIdentity.from_shell(state)

        async def release() -> None:
            await asyncio.to_thread(self._stop_state_blocking, state)

        handle = self.runtime.cleanup.begin(
            reservation,
            resource_id=f"{state.shell_id}:{id(state)}",
            phase="stop",
            factory=release,
            is_released=lambda: (
                state.native_closed.is_set()
                and state.reader_exited.is_set()
                and (state.reader_thread is None or not state.reader_thread.is_alive())
            ),
            kill_authorized=identity is not None,
        )
        handle.retain(state)
        state.cleanup_handle = handle
        report = await handle.wait(timeout=SHELL_STOP_WAIT_SECONDS)
        if report.complete:
            with self._registry_lock:
                self._shells.pop(state.shell_id, None)
        return report

    def _stop_finished(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()
        for shell_id, current in tuple(self._stop_tasks.items()):
            if current is task and not task.cancelled() and task.exception() is None:
                del self._stop_tasks[shell_id]

    @staticmethod
    def _stop_state_blocking(state: _ShellSession) -> None:
        with state.lock:
            state.termination = "forced"
        logger.info(
            "Stopping Shell PTY | shell=%s pid=%s reader_alive=%s",
            state.shell_id,
            state.pid,
            bool(state.reader_thread and state.reader_thread.is_alive()),
        )

        failures: list[BaseException] = []
        if state.pid is not None:
            identity = OwnedProcessIdentity.from_shell(state)
            if identity is not None and identity.still_matches():
                try:
                    if sys.platform == "win32":
                        subprocess.run(
                            ["taskkill", "/T", "/F", "/PID", str(identity.pid)],
                            capture_output=True,
                            timeout=SHELL_STOP_WAIT_SECONDS,
                        )
                except BaseException as exc:
                    failures.append(exc)

        reader = state.reader_thread
        if reader is None or reader.ident is None:
            state.reader_exited.set()

        # pywinpty 的 ConPTY reader 可能在 pty.read() 中阻塞；仅终止子进程
        # 不保证唤醒该读取。必须先在原生访问边界内关闭 PTY，再等待 reader
        # 收尾，否则“先等 reader、后 close”会把唤醒条件放在永远不会执行的后面。
        acquired = state.native_lock.acquire(timeout=SHELL_STOP_WAIT_SECONDS)
        if not acquired:
            failures.append(LifecycleFailure(f"Shell native lock did not become available: {state.shell_id}"))
        else:
            try:
                if not state.native_closed.is_set():
                    try:
                        exit_code = state.pty.exitstatus
                        with state.lock:
                            if exit_code is not None or state.exit_code is None:
                                state.exit_code = exit_code
                    except BaseException as exc:
                        failures.append(exc)
                    try:
                        state.pty.close(force=True)
                        state.native_closed.set()
                    except BaseException as exc:
                        failures.append(exc)
            finally:
                state.native_lock.release()

        if not state.reader_exited.wait(SHELL_STOP_WAIT_SECONDS):
            failures.append(LifecycleFailure(f"Shell reader did not stop: {state.shell_id}"))
        if reader is not None and reader.ident is not None:
            reader.join(timeout=SHELL_STOP_WAIT_SECONDS)
            if reader.is_alive():
                failures.append(LifecycleFailure(f"Shell reader thread is still alive: {state.shell_id}"))
        if failures:
            raise BaseExceptionGroup("Shell resource cleanup failed", failures)
        state.finish_output()
        with state.lock:
            state.running = False
            state.last_activity_at = time.time()
            state.version += 1
        logger.info(
            "Stopped Shell PTY | shell=%s reader_exited=%s native_closed=%s",
            state.shell_id,
            state.reader_exited.is_set(),
            state.native_closed.is_set(),
        )
        state.signal_output()

    def _get_owned(
        self,
        owner_session_id: str,
        character_name: str,
        shell_id: str
        ) -> _ShellSession:
        self._validate_owner(owner_session_id, character_name)
        if not shell_id:
            raise ShellAccessError("Shell not found")
        with self._registry_lock:
            canonical = self._canonical_owner_session_unlocked(owner_session_id)
            state = self._shells.get(shell_id)
            if (
                state is None
                or state.session_id != canonical
                or state.character_name != character_name
            ):
                raise ShellAccessError("Shell not found or inaccessible")
            return state

    def _canonical_owner_session(self, session_id: str) -> str:
        with self._registry_lock:
            return self._canonical_owner_session_unlocked(session_id)

    def _canonical_owner_session_unlocked(self, session_id: str) -> str:
        current = session_id
        seen: set[str] = set()
        while current in self._session_aliases:
            if current in seen:
                raise ShellError("Shell session alias cycle detected")
            seen.add(current)
            current = self._session_aliases[current]
        return current

    def _build_environment(
        self,
        shell_type: str,
    ) -> tuple[dict[str, str], dict[str, str]]:
        environment = dict(os.environ)
        environment["EVOLVE_PYTHON"] = sys.executable
        references: dict[str, str] = {}
        used_names: set[str] = {key.upper() for key in environment}
        fixed_names = {
            "ws": "EVOLVE_WS",
            "fork": "EVOLVE_FORK",
            "fix": "EVOLVE_FIX",
            "skills": "EVOLVE_SKILLS",
            "third": "EVOLVE_THIRD",
            "custom_hooks": "EVOLVE_CUSTOM_HOOKS",
            "custom_llm_client": "EVOLVE_CUSTOM_LLM_CLIENT",
            "custom_tools": "EVOLVE_CUSTOM_TOOLS",
        }
        for namespace, path in sorted(self.sandbox.namespace_bases().items()):
            fixed_env_name = fixed_names.get(namespace)
            if fixed_env_name is not None:
                env_name = fixed_env_name
            else:
                env_name = f"EVOLVE_NS_{namespace.upper()}"
                if env_name.upper() in used_names:
                    suffix = hashlib.sha256(namespace.encode("ascii")).hexdigest()[:8].upper()
                    env_name = f"{env_name}_{suffix}"
            used_names.add(env_name.upper())
            environment[env_name] = str(path)
            references[f"{namespace}:"] = self._environment_reference(shell_type, env_name)
        references["EVOLVE_PYTHON"] = self._environment_reference(
            shell_type, "EVOLVE_PYTHON"
        )
        return environment, references

    @staticmethod
    def _environment_reference(shell_type: str, env_name: str) -> str:
        return f"%{env_name}%" if shell_type == "cmd" else f"$env:{env_name}"

    @staticmethod
    def _resolve_shell(shell_type: str) -> tuple[str, list[str]]:
        ps_init = (
            "try { Remove-Module PSReadLine -ErrorAction Stop } "
            "catch { try { Set-PSReadLineOption -PredictionSource None "
            "-ErrorAction Stop } catch { $null = $_ } }"
        )
        programs = {
            "powershell": (
                "powershell.exe",
                ["-NoLogo", "-NoExit", "-NoProfile", "-Command", ps_init],
            ),
            "pwsh": (
                "pwsh.exe",
                ["-NoLogo", "-NoExit", "-NoProfile", "-Command", ps_init],
            ),
            "cmd": ("cmd.exe", ["/Q"]),
        }
        program, arguments = programs[shell_type]
        executable = shutil.which(program)
        if executable is None:
            raise ShellError(f"Shell executable not found: {program}")
        return executable, arguments

    @staticmethod
    def _validate_owner(owner_session_id: str, character_name: str) -> None:
        if not owner_session_id:
            raise ShellError("owner_session_id is required")
        if not character_name:
            raise ShellError("character_name is required")

    @staticmethod
    def _validate_line(
        text: str,
        *,
        allow_empty: bool,
        field: str
        ) -> None:
        if not allow_empty and not text:
            raise ShellError(f"{field} must not be empty")
        if "\r" in text or "\n" in text:
            raise ShellError(f"{field} must be a single line without CR/LF")

    @staticmethod
    def _require_running(state: _ShellSession) -> None:
        with state.lock:
            if state.closing.is_set() or not state.running:
                raise ShellError(f"Shell is not running: {state.shell_id}")

    @staticmethod
    def _total_chars(state: _ShellSession) -> int:
        with state.lock:
            return state.total_chars

    @staticmethod
    def _pty_is_alive(state: _ShellSession) -> bool:
        with state.native_lock:
            if state.native_closed.is_set():
                return False
            try:
                return bool(state.pty.isalive())
            except Exception:
                return False

    @staticmethod
    def _pty_is_eof(state: _ShellSession) -> bool:
        with state.native_lock:
            if state.native_closed.is_set():
                return True
            try:
                return bool(state.pty.eof())
            except Exception:
                return True
