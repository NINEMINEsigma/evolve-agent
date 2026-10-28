"""子进程编码与真实进程生命周期；同步执行仅限普通线程。"""

from __future__ import annotations

import asyncio
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from contextlib import asynccontextmanager, contextmanager
import locale
import logging
import os
import subprocess
import sys
import threading
import time
from typing import Any, AsyncIterator, Callable, Coroutine, Iterator, Mapping, Sequence, TypeVar

from entity.constant import (
    ApplicationState, SEARCH_PROCESS_STDERR_MAX_BYTES,
    SUBPROCESS_SOFT_CLEANUP_WAIT_TIME, SYSTEM_QUIESCE_TIMEOUT_SECONDS,
    SubprocessCreationState,
)
from entity.constant.timeouts import RESOURCE_CLEANUP_POLL_SECONDS
from entity.puretype import ProcessLineStreamResult
from entity.puretype.resource_cleanup import CleanupReport, CleanupWarning
from interface.runtime_system import IRuntimeSystem
from interface.subprocess_runner import ISubprocessRunner
from system.cleanup_errors import split_cleanup_timeouts
from system.lifecycle import ApplicationStoppingError, LifecycleFailure, close_resources
from system.process_termination import OwnedProcessIdentity, terminate_owned_tree
from system.resource_cleanup import CleanupProducer, ResourceCleanupHandle
from system.subprocess_operation import SubprocessOperation

logger = logging.getLogger(__name__)
_OutputT = TypeVar("_OutputT")
UTF8_ENV: dict[str, str] = {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}


def windows_process_group_flags() -> int:
    """Windows 自有进程使用独立进程组；其他平台保持既有行为。"""
    return subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0


def build_subprocess_env(extra_env: Mapping[str, str] | None = None, *, force_utf8_python: bool = True) -> dict[str, str]:
    env = os.environ.copy()
    if force_utf8_python:
        env.update(UTF8_ENV)
    if extra_env:
        env.update({str(k): str(v) for k, v in extra_env.items()})
    return env


def preferred_decode_encodings() -> list[str]:
    candidates = ["utf-8-sig", "utf-8"]
    # 标准流encoding是外部可替换对象的兼容边界，非项目模型字段。
    for encoding in (locale.getpreferredencoding(False), sys.getfilesystemencoding(), getattr(sys.stdout, "encoding", None)):
        if encoding:
            candidates.append(encoding)
    if sys.platform == "win32":
        candidates.extend(["gb18030", "gbk", "cp936", "mbcs"])
    candidates.extend(["utf-8", "latin-1"])
    seen: set[str] = set()
    result: list[str] = []
    for encoding in candidates:
        normalized = encoding.lower().replace("_", "-")
        if normalized not in seen:
            seen.add(normalized)
            result.append(encoding)
    return result


def safe_decode(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if not data:
        return ""
    for encoding in preferred_decode_encodings():
        try:
            return data.decode(encoding, errors="strict")
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


def completed_process_from_bytes(*, args: Sequence[str] | str, returncode: int | None,
                                 stdout: bytes | str | None, stderr: bytes | str | None) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=args, returncode=returncode if returncode is not None else -1,
                                       stdout=safe_decode(stdout), stderr=safe_decode(stderr))


def run_text(args: Sequence[str] | str, *, timeout: float | None = None,
             env: Mapping[str, str] | None = None, stderr_to_stdout: bool = False,
             force_utf8_python: bool = True, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT if stderr_to_stdout else subprocess.PIPE,
                          text=False, timeout=timeout, env=build_subprocess_env(env, force_utf8_python=force_utf8_python), **kwargs)
    return completed_process_from_bytes(args=args, returncode=proc.returncode, stdout=proc.stdout,
                                        stderr=None if stderr_to_stdout else proc.stderr)


def _kill_proc_tree(pid: int) -> None:
    """旧裸PID辅助入口；所有Runner清理和提前截断均禁止使用此入口。"""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
    else:
        import signal
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except ProcessLookupError:
            pass


class SubprocessRunner(ISubprocessRunner):
    """Own creation, consumer handoff and one real cleanup per subprocess."""

    def __init__(self) -> None:
        super().__init__(dependencies=(IRuntimeSystem,))
        self._active_procs: dict[str, list[SubprocessOperation]] = {}
        self._operations: set[SubprocessOperation] = set()
        self._retained_operations: set[SubprocessOperation] = set()
        self._settled_operations: set[SubprocessOperation] = set()
        self._spawning: set[asyncio.Task[asyncio.subprocess.Process]] = set()
        self._procs_lock = threading.Lock()
        self._idle = threading.Event()
        self._idle.set()
        self._cleanup_failures: list[BaseException] = []
        self._admission_closed = False
        self._runtime: IRuntimeSystem | None = None
        self._cleanup_producer: CleanupProducer | None = None

    async def virtual_awake(self) -> None:
        self._runtime = self.get_system(IRuntimeSystem)
        self._cleanup_producer = self.runtime.cleanup.open_producer(owner="SubprocessRunner", loop=asyncio.get_running_loop())

    @property
    def runtime(self) -> IRuntimeSystem:
        if self._runtime is None:
            raise LifecycleFailure("SubprocessRunner has not been awakened")
        return self._runtime

    def _refresh_idle_locked(self) -> None:
        if self._operations or self._active_procs or self._retained_operations or self._spawning:
            self._idle.clear()
        else:
            self._idle.set()

    def _begin_operation(self, session_id: str) -> SubprocessOperation:
        with self.runtime.admission():
            with self._procs_lock:
                if self._admission_closed:
                    raise ApplicationStoppingError("Subprocess admission has been closed")
            producer = self._cleanup_producer
            if producer is None:
                raise LifecycleFailure("Subprocess cleanup producer has not been opened")
            reservation = producer.reserve()
            try:
                operation = SubprocessOperation(session_id=session_id, reservation=reservation)
                with self._procs_lock:
                    self._operations.add(operation)
                    self._refresh_idle_locked()
                return operation
            except BaseException:
                reservation.release()
                raise

    def _remove_operation_locked(self, operation: SubprocessOperation) -> None:
        bucket = self._active_procs.get(operation.session_id)
        if bucket is not None and operation in bucket:
            bucket.remove(operation)
            if not bucket:
                del self._active_procs[operation.session_id]
        self._retained_operations.discard(operation)
        self._settled_operations.discard(operation)

    def _finish_operation(self, operation: SubprocessOperation) -> None:
        operation.mark_body_finished()
        with self._procs_lock:
            self._operations.discard(operation)
            if operation in self._settled_operations:
                self._remove_operation_locked(operation)
            else:
                self._retained_operations.add(operation)
            self._refresh_idle_locked()

    def _mark_operation_settled(self, operation: SubprocessOperation) -> None:
        with self._procs_lock:
            if operation in self._operations:
                self._settled_operations.add(operation)
            else:
                self._remove_operation_locked(operation)
            self._refresh_idle_locked()

    def _on_process_released(self, operation: SubprocessOperation) -> None:
        self._mark_operation_settled(operation)

    def _release_uncreated_operation(self, operation: SubprocessOperation) -> None:
        if operation.spawn_task is not None and not operation.spawn_task.done():
            raise LifecycleFailure("Subprocess creation has not finished")
        if operation.claim_uncreated_release():
            operation.reservation.release()
            self._mark_operation_settled(operation)

    def _register_process(self, operation: SubprocessOperation,
                          process: subprocess.Popen[bytes] | asyncio.subprocess.Process) -> bool:
        operation.bind_process(process)
        identity = OwnedProcessIdentity.from_popen(process) if isinstance(process, subprocess.Popen) else OwnedProcessIdentity.from_asyncio(process)
        operation.bind_identity(identity)
        with self._procs_lock:
            self._active_procs.setdefault(operation.session_id, []).append(operation)
            self._refresh_idle_locked()
            closing = self._admission_closed
        return closing or self.runtime.state is not ApplicationState.RUNNING

    def _record_cleanup_failure(self, error: BaseException) -> None:
        _timeouts, remaining = split_cleanup_timeouts(error)
        if remaining is None:
            return
        with self._procs_lock:
            if not any(item is error for item in self._cleanup_failures):
                self._cleanup_failures.append(error)
        self.runtime.record_failure(error)

    def _process_key(self, operation: SubprocessOperation) -> str:
        proc = operation.process
        if proc is None:
            raise LifecycleFailure("Subprocess operation has no process")
        return f"{type(proc).__name__}:{id(proc)}:{proc.pid}"

    def _request_process_cleanup(self, operation: SubprocessOperation) -> Future[ResourceCleanupHandle]:
        submission, claimed = operation.claim_cleanup_submission()
        if not claimed:
            return submission
        try:
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is self.runtime.loop:
                self._start_process_cleanup(operation, submission)
            else:
                self.runtime.loop.call_soon_threadsafe(self._start_process_cleanup, operation, submission)
        except BaseException as error:
            if not submission.done():
                submission.set_exception(error)
            self._record_cleanup_failure(error)
        return submission

    def _start_process_cleanup(self, operation: SubprocessOperation,
                               submission: Future[ResourceCleanupHandle]) -> None:
        try:
            handle = self.runtime.cleanup.begin(
                operation.reservation, resource_id=self._process_key(operation), phase="terminate",
                factory=lambda: self._release_process(operation), is_released=operation.is_released,
                kill_authorized=operation.identity is not None,
            )
            handle.retain(operation)
            operation.attach_cleanup_handle(handle)
            handle.release_observed.add_done_callback(lambda _done: self._on_process_released(operation))
        except BaseException as error:
            submission.set_exception(error)
            self._record_cleanup_failure(error)
        else:
            submission.set_result(handle)

    async def _release_process(self, operation: SubprocessOperation) -> None:
        proc = operation.process
        if proc is None:
            raise LifecycleFailure("Cannot clean up an uncreated subprocess")
        alive = proc.poll() is None if isinstance(proc, subprocess.Popen) else proc.returncode is None
        if alive:
            if operation.identity is not None:
                await terminate_owned_tree(operation.identity)
            else:
                logger.warning("Subprocess cleanup pending: identity unavailable | session=%s resource=%s",
                               operation.session_id, self._process_key(operation))
        await asyncio.shield(asyncio.wrap_future(operation.io_finished))
        if isinstance(proc, subprocess.Popen):
            def finish_native() -> None:
                streams = (proc.stdin, proc.stdout, proc.stderr)
                if any(stream is not None and not stream.closed for stream in streams):
                    proc.communicate()
                proc.wait()
                for stream in streams:
                    if stream is not None:
                        stream.close()
            operation.native_cleanup_task = asyncio.create_task(asyncio.to_thread(finish_native), name="subprocess-native-cleanup")
            operation.native_cleanup_task.add_done_callback(self._observe_cleanup_task)
            await asyncio.shield(operation.native_cleanup_task)
        else:
            async def discard(reader: asyncio.StreamReader | None) -> None:
                if reader is not None:
                    while await reader.read(4096):
                        pass
            if proc.stdin is not None:
                proc.stdin.close()
                await proc.stdin.wait_closed()
            async with asyncio.TaskGroup() as group:
                group.create_task(discard(proc.stdout))
                group.create_task(discard(proc.stderr))
                group.create_task(proc.wait())
        operation.mark_resources_closed()

    def _observe_cleanup_task(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            self._record_cleanup_failure(LifecycleFailure("Subprocess cleanup task was cancelled"))
        else:
            error = task.exception()
            if error is not None:
                self._record_cleanup_failure(error)

    def _pending_report(self, operation: SubprocessOperation) -> CleanupReport:
        warning = CleanupWarning(owner="SubprocessRunner", resource_id=self._process_key(operation), phase="submit",
                                 timeout_seconds=SUBPROCESS_SOFT_CLEANUP_WAIT_TIME,
                                 message="Subprocess cleanup registration is still pending")
        logger.warning("%s | session=%s resource=%s", warning.message, operation.session_id, warning.resource_id)
        return CleanupReport(complete=False, pending_resources=[warning.resource_id], warnings=[warning])

    def _observe_process_release_sync(self, operation: SubprocessOperation) -> CleanupReport:
        deadline = time.monotonic() + SUBPROCESS_SOFT_CLEANUP_WAIT_TIME
        submission = self._request_process_cleanup(operation)
        try:
            handle = submission.result(max(0.0, deadline - time.monotonic()))
        except FutureTimeoutError:
            if submission.done():
                raise
            return self._pending_report(operation)
        return handle.wait_sync(timeout=max(0.0, deadline - time.monotonic()))

    async def _observe_process_release(self, operation: SubprocessOperation) -> CleanupReport:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + SUBPROCESS_SOFT_CLEANUP_WAIT_TIME
        submission = self._request_process_cleanup(operation)
        adapted = asyncio.wrap_future(submission)
        adapted.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            handle = await asyncio.wait_for(asyncio.shield(adapted), max(0.0, deadline - loop.time()))
        except TimeoutError:
            if submission.done():
                raise
            return self._pending_report(operation)
        return await handle.wait(timeout=max(0.0, deadline - loop.time()))

    def _register_io_tasks(self, operation: SubprocessOperation, tasks: tuple[asyncio.Task[Any], ...]) -> None:
        if any(task in operation.io_tasks for task in tasks):
            raise LifecycleFailure("Subprocess consumer was registered twice")
        operation.io_tasks += tasks

    def _create_io_task(self, operation: SubprocessOperation, coroutine: Coroutine[Any, Any, _OutputT], *, name: str) -> asyncio.Task[_OutputT]:
        try:
            task = asyncio.create_task(coroutine, name=name)
        except BaseException:
            coroutine.close()
            raise
        # 每创建一个就立即交接，后续任务工厂失败时不能漏掉已活跃的reader。
        self._register_io_tasks(operation, (task,))
        return task

    def _start_io_handoff(self, operation: SubprocessOperation, *, cancel_readers: bool) -> asyncio.Task[None]:
        if operation.io_join_task is None:
            operation.io_join_task = asyncio.create_task(
                self._join_io_tasks(operation, cancel_readers=cancel_readers), name="subprocess-io-handoff")
            operation.io_join_task.add_done_callback(self._observe_cleanup_task)
        return operation.io_join_task

    async def _join_io_tasks(self, operation: SubprocessOperation, *, cancel_readers: bool) -> None:
        if cancel_readers:
            for task in operation.io_tasks:
                if not task.done():
                    task.cancel()
        # 消费者异常由原执行入口取得；此任务只证明真实消费者已经退出。
        await asyncio.gather(*operation.io_tasks, return_exceptions=True)
        operation.mark_io_finished()

    async def _create_process(self, args: list[str], popen_kwargs: dict,
                              operation: SubprocessOperation) -> asyncio.subprocess.Process:
        try:
            proc = await asyncio.create_subprocess_exec(*args, **popen_kwargs)
        except BaseException as error:
            operation.fail_creation(error)
            raise
        try:
            if self._register_process(operation, proc):
                operation.abandon_consumer()
                raise ApplicationStoppingError("Subprocess created while application was stopping")
        except BaseException as error:
            operation.creation_error = error
            operation.abandon_consumer()
            raise
        return proc

    def _settle_spawn_handoff(self, operation: SubprocessOperation) -> None:
        if operation.process is None:
            return
        if operation.state is SubprocessCreationState.CLAIMED:
            return
        if operation.abandoned or operation.creation_error is not None or self.runtime.state is not ApplicationState.RUNNING:
            operation.abandon_consumer()
            operation.mark_io_finished()
            self._request_process_cleanup(operation)

    def _abandon_spawn(self, operation: SubprocessOperation) -> None:
        operation.abandon_consumer()
        self._settle_spawn_handoff(operation)
        error = operation.creation_error
        if error is not None and not isinstance(error, (ApplicationStoppingError, asyncio.CancelledError)):
            # 完成回调可能已先执行；放弃方也负责补交付无人接收的原创建错误。
            self._record_cleanup_failure(error)

    def _spawn_finished(self, operation: SubprocessOperation, task: asyncio.Task[asyncio.subprocess.Process]) -> None:
        error = LifecycleFailure("Subprocess creation task was cancelled") if task.cancelled() else task.exception()
        if operation.process is None:
            self._release_uncreated_operation(operation)
        else:
            self._settle_spawn_handoff(operation)
        with self._procs_lock:
            self._spawning.discard(task)
            self._refresh_idle_locked()
        if error is not None and operation.abandoned and not isinstance(error, (ApplicationStoppingError, asyncio.CancelledError)):
            self._record_cleanup_failure(error)
        elif error is not None and task.cancelled():
            self._record_cleanup_failure(error)

    async def _spawn_async(self, args: list[str], popen_kwargs: dict,
                           operation: SubprocessOperation) -> asyncio.subprocess.Process:
        coroutine = self._create_process(args, popen_kwargs, operation)
        try:
            task = asyncio.create_task(coroutine, name="subprocess-create")
        except BaseException as error:
            coroutine.close()
            operation.fail_creation(error)
            self._release_uncreated_operation(operation)
            raise
        operation.spawn_task = task
        with self._procs_lock:
            self._spawning.add(task)
            self._refresh_idle_locked()
        task.add_done_callback(lambda done: self._spawn_finished(operation, done))
        try:
            proc = await asyncio.shield(task)
            if not operation.claim_consumer():
                raise ApplicationStoppingError("Subprocess creation was abandoned")
            return proc
        except asyncio.CancelledError:
            self._abandon_spawn(operation)
            raise

    @contextmanager
    def _sync_process(self, args: list[str], popen_kwargs: dict, session_id: str) -> Iterator[subprocess.Popen[bytes]]:
        operation = self._begin_operation(session_id)
        try:
            try:
                proc = subprocess.Popen[bytes](args, text=False, **popen_kwargs)
            except BaseException as error:
                operation.fail_creation(error)
                self._release_uncreated_operation(operation)
                raise
            if self._register_process(operation, proc):
                raise ApplicationStoppingError("Subprocess created while application was stopping")
            operation.claim_consumer()
            yield proc
        finally:
            original = sys.exception()
            try:
                if operation.process is not None:
                    operation.mark_io_finished()
                    self._observe_process_release_sync(operation)
            except BaseException as error:
                self._record_cleanup_failure(error)
                if original is not None and original is not error:
                    raise BaseExceptionGroup("Subprocess cleanup failed", [original, error]) from None
                raise
            finally:
                self._finish_operation(operation)

    @asynccontextmanager
    async def _async_process(self, args: list[str], popen_kwargs: dict, session_id: str) -> AsyncIterator[SubprocessOperation]:
        operation = self._begin_operation(session_id)
        try:
            await self._spawn_async(args, popen_kwargs, operation)
            yield operation
        finally:
            original = sys.exception()
            try:
                if operation.process is not None:
                    self._start_io_handoff(operation, cancel_readers=original is not None)
                    await self._observe_process_release(operation)
            except asyncio.CancelledError:
                # 创建/消费者/释放由各自持有者继续收尾，不能把再次取消当成释放完成。
                raise
            except BaseException as error:
                self._record_cleanup_failure(error)
                if original is not None and original is not error:
                    raise BaseExceptionGroup("Subprocess cleanup failed", [original, error]) from None
                raise
            finally:
                self._finish_operation(operation)

    @staticmethod
    def _require_sync_thread() -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        raise LifecycleFailure("Blocking subprocess execution requires a non-event-loop thread")

    def _require_owner_loop(self) -> None:
        if asyncio.get_running_loop() is not self.runtime.loop:
            raise LifecycleFailure("Async subprocess execution requires the runtime loop")

    @staticmethod
    def _popen_kwargs(cwd: str, extra_env: dict[str, str] | None) -> dict:
        kwargs: dict = {"cwd": cwd, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
                        "env": build_subprocess_env(extra_env)}
        if sys.platform == "win32":
            kwargs["creationflags"] = windows_process_group_flags()
        return kwargs

    def run(self, args: list[str], *, cwd: str, timeout: float | None = None,
            extra_env: dict[str, str] | None = None, session_id: str = "") -> subprocess.CompletedProcess[str]:
        self._require_sync_thread()
        if not args:
            raise ValueError("subprocess args must not be empty")
        logger.debug("SubprocessRunner.run | cwd=%s cmd=%s", cwd, args)
        with self._sync_process(args, self._popen_kwargs(cwd, extra_env), session_id) as proc:
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as error:
                raise subprocess.TimeoutExpired(cmd=args[0], timeout=timeout if timeout is not None else 0,
                                                output="", stderr="") from error
            return completed_process_from_bytes(args=args, returncode=proc.returncode, stdout=stdout, stderr=stderr)

    async def run_async(self, args: list[str], *, cwd: str, timeout: float | None = None,
                        extra_env: dict[str, str] | None = None, session_id: str = "") -> subprocess.CompletedProcess[str]:
        self._require_owner_loop()
        if not args:
            raise ValueError("subprocess args must not be empty")
        logger.debug("SubprocessRunner.run_async | cwd=%s cmd=%s", cwd, args)
        async with self._async_process(args, self._popen_kwargs(cwd, extra_env), session_id) as operation:
            proc = operation.process
            if not isinstance(proc, asyncio.subprocess.Process):
                raise LifecycleFailure("Async subprocess was not created")
            if proc.stdout is None or proc.stderr is None:
                raise LifecycleFailure("Async subprocess output pipes were not created")
            stdout_reader = self._create_io_task(operation, proc.stdout.read(), name="subprocess-stdout")
            stderr_reader = self._create_io_task(operation, proc.stderr.read(), name="subprocess-stderr")

            async def collect_output() -> tuple[bytes, bytes]:
                done, _ = await asyncio.wait({stdout_reader, stderr_reader}, return_when=asyncio.FIRST_EXCEPTION)
                for reader in done:
                    reader.result()
                await proc.wait()
                return stdout_reader.result(), stderr_reader.result()

            # 不依赖communicate内部gather的取消语义；直接持有两条真实reader。
            consumer = self._create_io_task(operation, collect_output(), name="subprocess-communicate")
            try:
                stdout, stderr = await asyncio.wait_for(asyncio.shield(consumer), timeout)
            except TimeoutError as error:
                raise subprocess.TimeoutExpired(cmd=args[0], timeout=timeout if timeout is not None else 0,
                                                output="", stderr="") from error
            return completed_process_from_bytes(args=args, returncode=proc.returncode, stdout=stdout, stderr=stderr)

    async def run_async_line_processor(
        self, args: list[str], *, cwd: str, on_stdout_line: Callable[[bytes], bool],
        timeout: float | None = None, extra_env: dict[str, str] | None = None,
        session_id: str = "", stderr_byte_limit: int = SEARCH_PROCESS_STDERR_MAX_BYTES,
    ) -> ProcessLineStreamResult:
        self._require_owner_loop()
        if not args:
            raise ValueError("subprocess args must not be empty")
        logger.debug("SubprocessRunner.run_async_line_processor | cwd=%s cmd=%s", cwd, args)
        async with self._async_process(args, self._popen_kwargs(cwd, extra_env), session_id) as operation:
            proc = operation.process
            if not isinstance(proc, asyncio.subprocess.Process):
                raise LifecycleFailure("Async subprocess was not created")
            stderr_chunks: list[bytes] = []
            stderr_seen = 0
            stderr_truncated = False
            stdout_line_count = 0
            truncated = False

            async def read_stderr() -> None:
                nonlocal stderr_seen, stderr_truncated
                if proc.stderr is None:
                    raise LifecycleFailure("Subprocess stderr pipe was not created")
                while chunk := await proc.stderr.read(4096):
                    if stderr_seen < stderr_byte_limit:
                        stderr_chunks.append(chunk[:stderr_byte_limit - stderr_seen])
                    stderr_seen += len(chunk)
                    stderr_truncated = stderr_seen > stderr_byte_limit

            async def read_stdout() -> None:
                nonlocal stdout_line_count, truncated
                if proc.stdout is None:
                    raise LifecycleFailure("Subprocess stdout pipe was not created")
                while line := await proc.stdout.readline():
                    if truncated:
                        continue
                    stdout_line_count += 1
                    if not on_stdout_line(line):
                        truncated = True
                        self._request_process_cleanup(operation)
                        while await proc.stdout.read(4096):
                            pass
                        return

            stdout_task = self._create_io_task(operation, read_stdout(), name="subprocess-stdout")
            stderr_task = self._create_io_task(operation, read_stderr(), name="subprocess-stderr")
            try:
                await asyncio.wait_for(asyncio.shield(stdout_task), timeout)
                await asyncio.wait_for(proc.wait(), SUBPROCESS_SOFT_CLEANUP_WAIT_TIME if truncated else timeout)
                await asyncio.wait_for(asyncio.shield(stderr_task), SUBPROCESS_SOFT_CLEANUP_WAIT_TIME)
            except TimeoutError as error:
                raise subprocess.TimeoutExpired(cmd=args[0], timeout=timeout if timeout is not None else 0,
                                                output="", stderr="") from error
            finally:
                original = sys.exception()
                handoff = self._start_io_handoff(operation, cancel_readers=original is not None)
                await asyncio.shield(handoff)
                failures = [task.exception() for task in (stdout_task, stderr_task)
                            if not task.cancelled() and task.exception() is not None and task.exception() is not original]
                if failures:
                    if original is not None:
                        failures.insert(0, original)
                    raise BaseExceptionGroup("Subprocess output processing failed", failures)
            stderr_text = safe_decode(b"".join(stderr_chunks))
            if stderr_truncated:
                stderr_text += "\n[stderr truncated]"
            return ProcessLineStreamResult(returncode=proc.returncode, stderr=stderr_text,
                                           truncated=truncated, stdout_line_count=stdout_line_count)

    def close_admission(self) -> None:
        with self._procs_lock:
            self._admission_closed = True

    def kill_active(self, session_id: str) -> None:
        with self._procs_lock:
            operations = list(self._active_procs.get(session_id, ())) if session_id else [op for bucket in self._active_procs.values() for op in bucket]
        for operation in operations:
            self._request_process_cleanup(operation)

    async def terminate_all(self) -> None:
        self.close_admission()
        if self._cleanup_producer is not None:
            self._cleanup_producer.close()
        # 也覆盖绑定进程后会话索引登记失败的操作。
        with self._procs_lock:
            operations = tuple(self._operations | self._retained_operations)
        observations = [self._observe_process_release(op) for op in operations if op.process is not None]
        if observations:
            results = await asyncio.gather(*observations, return_exceptions=True)
            failures = [result for result in results if isinstance(result, BaseException)]
            if failures:
                raise BaseExceptionGroup("Subprocess termination failed", failures)

    async def wait_idle(self) -> None:
        self.close_admission()
        await asyncio.to_thread(self._idle.wait, SYSTEM_QUIESCE_TIMEOUT_SECONDS)
        with self._procs_lock:
            failures = list(self._cleanup_failures)
            active = bool(self._operations or self._spawning)
        if active:
            failures.append(LifecycleFailure("Subprocess operations did not finish before the deadline"))
        if failures:
            raise BaseExceptionGroup("Subprocess cleanup failed", failures)
        # 只剩纯资源pending时由registry最终drain继续等真实清理。

    async def virtual_shotdown(self) -> None:
        await close_resources((self.terminate_all, self.wait_idle))
