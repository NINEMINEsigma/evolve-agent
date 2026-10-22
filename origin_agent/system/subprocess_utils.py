"""子进程 I/O 编码工具。

统一处理跨平台子进程输出，避免 Windows 本地编码、UTF-8 工具链和
Python 子进程默认编码之间互相冲突。
"""

from __future__ import annotations

import asyncio
import locale
import logging
import os
import subprocess  # nosec
import sys
import threading
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncIterator, Callable, Iterator, Mapping, Sequence

from framework import AsyncSystem

from concurrent.futures import Future
from entity.constant import (
    ApplicationState,
    SEARCH_PROCESS_STDERR_MAX_BYTES,
    SUBPROCESS_SOFT_CLEANUP_WAIT_TIME,
    SYSTEM_QUIESCE_TIMEOUT_SECONDS,
)
from entity.puretype import ProcessLineStreamResult
from entity.puretype.resource_cleanup import CleanupWarning
from system.cleanup_errors import ResourceCleanupTimeout, split_cleanup_timeouts
from system.lifecycle import ApplicationStoppingError, LifecycleFailure, close_resources
from system.process_termination import OwnedProcessIdentity, terminate_owned_tree
from system.resource_cleanup import CleanupProducer, CleanupReservation, ResourceCleanupHandle
from interface.runtime_system import IRuntimeSystem
from interface.subprocess_runner import ISubprocessRunner

logger = logging.getLogger(__name__)


UTF8_ENV: dict[str, str] = {
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUTF8": "1",
}


def windows_process_group_flags() -> int:
    """返回 Windows 下用于创建独立进程组的 creationflags。

    ``CREATE_NEW_PROCESS_GROUP`` 使子进程成为新进程组的根，
    便于后续用 ``taskkill /T`` 或 ``CTRL_BREAK_EVENT`` 终止整棵进程树。
    非 Windows 平台返回 0（无操作）。
    """
    if sys.platform == "win32":
        return subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    return 0


def build_subprocess_env(
    extra_env: Mapping[str, str] | None = None,
    *,
    force_utf8_python: bool = True,
) -> dict[str, str]:
    """返回适合子进程使用的环境变量。"""
    env = os.environ.copy()
    if force_utf8_python:
        env.update(UTF8_ENV)
    if extra_env:
        env.update({str(k): str(v) for k, v in extra_env.items()})
    return env


def preferred_decode_encodings() -> list[str]:
    """返回稳定的解码候选链。"""
    candidates: list[str] = ["utf-8-sig", "utf-8"]

    locale_encoding = locale.getpreferredencoding(False)
    filesystem_encoding = sys.getfilesystemencoding()
    stdout_encoding = getattr(sys.stdout, "encoding", None)

    for encoding in (locale_encoding, filesystem_encoding, stdout_encoding):
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
    """将子进程输出安全解码为文本，永不因编码错误抛异常。"""
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


def completed_process_from_bytes(
    *,
    args: Sequence[str] | str,
    returncode: int | None,
    stdout: bytes | str | None,
    stderr: bytes | str | None
    ) -> subprocess.CompletedProcess[str]:
    """把 bytes 输出转换为文本版 CompletedProcess。"""
    return subprocess.CompletedProcess(
        args=args,
        returncode=returncode if returncode is not None else -1,
        stdout=safe_decode(stdout),
        stderr=safe_decode(stderr),
    )


def run_text(
    args: Sequence[str] | str,
    *,
    timeout: float | None = None,
    env: Mapping[str, str] | None = None,
    stderr_to_stdout: bool = False,
    force_utf8_python: bool = True,
    **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
    """以 bytes 模式运行子进程，并返回安全解码后的文本结果。"""
    merged_env = build_subprocess_env(env, force_utf8_python=force_utf8_python)
    stderr = subprocess.STDOUT if stderr_to_stdout else subprocess.PIPE
    proc = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=stderr,
        text=False,
        timeout=timeout,
        env=merged_env,
        **kwargs,
    )
    return completed_process_from_bytes(
        args=args,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=None if stderr_to_stdout else proc.stderr,
    )


# --------------------------------------------------------------------------- #
# 进程树终止
# --------------------------------------------------------------------------- #


def _kill_proc_tree(pid: int) -> None:
    """强制终止进程及其所有子孙进程。

    禁止用于本任务资源清理。SubprocessRunner、ShellManager、BrowserSystem、
    LSPManager 的新清理路径必须使用已证明身份的 terminate_owned_tree。
    Windows 使用 ``taskkill /T /F``。
    Unix 向进程组发送 SIGTERM。
    """
    if sys.platform == "win32":
        subprocess.run(  # nosec
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            capture_output=True,
        )
    else:
        try:
            import signal

            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except ProcessLookupError:
            pass


# --------------------------------------------------------------------------- #
# SubprocessRunner — 子进程执行层（同步 + 真异步）
# --------------------------------------------------------------------------- #


class SubprocessRunner(ISubprocessRunner):
    """子进程执行的唯一实现层，持有活动进程登记表与进程树终止逻辑。

    注册为 framework AsyncSystem，依赖 RuntimeSystem；由 Application 在
    P22 装配后经 ``app.get_system(ISubprocessRunner)`` 取得。提供同步
    ``run()``（任意线程可用）与真异步 ``run_async()``（事件循环内 await）。
   活动进程按 ``session_id`` 分桶登记，供中断路径 ``kill_active()`` 按会话终止。
    """

    def __init__(self) -> None:
        super().__init__(dependencies=(IRuntimeSystem,))
        # session_id -> [Popen | asyncio.subprocess.Process]；kill_active 终止用。
        self._active_procs: dict[str, list[subprocess.Popen | asyncio.subprocess.Process]] = {}
        self._procs_lock: threading.Lock = threading.Lock()
        self._operations: set[Future[None]] = set()
        self._spawning: set[asyncio.Task[asyncio.subprocess.Process]] = set()
        self._idle = threading.Event()
        self._idle.set()
        self._cleanup_failures: list[BaseException] = []
        self._admission_closed = False
        self._runtime: IRuntimeSystem | None = None
        self._cleanup_producer: CleanupProducer | None = None
        self._process_reservations: dict[
            subprocess.Popen | asyncio.subprocess.Process, CleanupReservation
        ] = {}
        self._process_handles: dict[
            subprocess.Popen | asyncio.subprocess.Process, ResourceCleanupHandle
        ] = {}

    async def virtual_awake(self) -> None:
        self._runtime = self.get_system(IRuntimeSystem)
        self._cleanup_producer = self.runtime.cleanup.open_producer(
            owner="SubprocessRunner",
            loop=asyncio.get_running_loop(),
        )

    @property
    def runtime(self) -> IRuntimeSystem:
        if self._runtime is None:
            raise LifecycleFailure("SubprocessRunner has not been awakened")
        return self._runtime

    def _begin_operation(self) -> Future[None]:
        with self.runtime.admission():
            with self._procs_lock:
                if self._admission_closed:
                    raise ApplicationStoppingError("Subprocess admission has been closed")
                operation: Future[None] = Future()
                self._operations.add(operation)
                self._idle.clear()
                return operation

    def _finish_operation(self, operation: Future[None]) -> None:
        with self._procs_lock:
            self._operations.remove(operation)
            operation.set_result(None)
            if not self._operations and not self._active_procs and not self._spawning:
                self._idle.set()

    def _register_process(
        self,
        session_id: str,
        proc: subprocess.Popen | asyncio.subprocess.Process
        ) -> bool:
        with self._procs_lock:
            self._active_procs.setdefault(session_id, []).append(proc)
            self._idle.clear()
            closed = self._admission_closed
        # 创建期间可能已STOPPING且kill_active快照尚看不到此进程。
        # 先登记再核对Runtime，保证迟到进程由创建方立即收回；不反转锁序。
        return closed or self.runtime.state != ApplicationState.RUNNING

    def _forget_process(
        self,
        session_id: str,
        proc: subprocess.Popen | asyncio.subprocess.Process
        ) -> None:
        with self._procs_lock:
            processes = self._active_procs[session_id]
            processes.remove(proc)
            if not processes:
                del self._active_procs[session_id]
            if not self._operations and not self._active_procs and not self._spawning:
                self._idle.set()

    def _record_cleanup_failure(self, error: BaseException) -> None:
        _timeouts, remaining = split_cleanup_timeouts(error)
        if remaining is None:
            return
        with self._procs_lock:
            self._cleanup_failures.append(remaining)
        self.runtime.record_failure(remaining)

    def _reserve_cleanup(self) -> CleanupReservation:
        producer = self._cleanup_producer
        if producer is None:
            raise LifecycleFailure("Subprocess cleanup producer has not been opened")
        return producer.reserve()

    def _process_key(
        self,
        proc: subprocess.Popen | asyncio.subprocess.Process,
    ) -> str:
        return f"{type(proc).__name__}:{id(proc)}:{proc.pid}"

    def _process_released(
        self,
        proc: subprocess.Popen | asyncio.subprocess.Process,
    ) -> bool:
        if isinstance(proc, subprocess.Popen):
            return proc.poll() is not None
        return proc.returncode is not None

    async def _release_registered_process(
        self,
        session_id: str,
        proc: subprocess.Popen | asyncio.subprocess.Process,
        reservation: CleanupReservation,
    ) -> ResourceCleanupHandle:
        identity = (
            OwnedProcessIdentity.from_popen(proc)
            if isinstance(proc, subprocess.Popen)
            else OwnedProcessIdentity.from_asyncio(proc)
        )

        async def release() -> None:
            if identity is None:
                raise ResourceCleanupTimeout(CleanupWarning(
                    owner="SubprocessRunner",
                    resource_id=self._process_key(proc),
                    phase="identity",
                    timeout_seconds=SUBPROCESS_SOFT_CLEANUP_WAIT_TIME,
                    message="Owned subprocess identity could not be proven",
                ))
            if not self._process_released(proc):
                await terminate_owned_tree(identity)
            if isinstance(proc, subprocess.Popen):
                await asyncio.to_thread(proc.wait)
            else:
                await proc.wait()

        handle = self.runtime.cleanup.begin(
            reservation,
            resource_id=self._process_key(proc),
            phase="terminate",
            factory=release,
            is_released=lambda: self._process_released(proc),
            kill_authorized=identity is not None,
        )
        handle.retain(proc)
        self._process_handles[proc] = handle
        return handle

    async def _observe_process_release(
        self,
        session_id: str,
        proc: subprocess.Popen | asyncio.subprocess.Process,
        reservation: CleanupReservation,
    ) -> None:
        handle = await self._release_registered_process(session_id, proc, reservation)
        report = await handle.wait(timeout=SUBPROCESS_SOFT_CLEANUP_WAIT_TIME)
        if report.complete:
            self._forget_process(session_id, proc)
            return
        if self._process_released(proc):
            return
        raise ResourceCleanupTimeout(CleanupWarning(
            owner="SubprocessRunner",
            resource_id=handle.resource_id,
            phase=handle.phase,
            timeout_seconds=SUBPROCESS_SOFT_CLEANUP_WAIT_TIME,
            message="Subprocess resource cleanup is still pending",
        ))

    def close_admission(self) -> None:
        with self._procs_lock:
            self._admission_closed = True

    async def terminate_all(self) -> None:
        """关闭接收并终止已登记进程；启动中的操作会在登记后自行终止。"""
        self.close_admission()
        if self._cleanup_producer is not None:
            self._cleanup_producer.close()
        with self._procs_lock:
            processes = [proc for bucket in self._active_procs.values() for proc in bucket]
        handles = [
            self._process_handles[proc]
            for proc in processes
            if proc in self._process_handles
        ]
        if handles:
            await self.runtime.cleanup.wait_many(
                handles,
                timeout=SUBPROCESS_SOFT_CLEANUP_WAIT_TIME,
            )

    async def wait_idle(self) -> None:
        self.close_admission()
        idle = await asyncio.to_thread(self._idle.wait, SYSTEM_QUIESCE_TIMEOUT_SECONDS)
        with self._procs_lock:
            failures = list(self._cleanup_failures)
            pending = bool(self._process_handles) or bool(self._operations) or bool(self._spawning)
        if not idle and (self._operations or self._spawning):
            failures.append(LifecycleFailure("Subprocess operations did not finish before the deadline"))
        elif pending:
            return
        if failures:
            raise BaseExceptionGroup("Subprocess cleanup failed", failures)

    async def _spawn_async(
        self,
        args: list[str],
        popen_kwargs: dict,
        session_id: str
        ) -> asyncio.subprocess.Process:
        """由实际创建任务登记进程，调用方取消不会遗漏已创建的进程。"""
        async def spawn() -> asyncio.subprocess.Process:
            proc = await asyncio.create_subprocess_exec(*args, **popen_kwargs)
            reservation = self._reserve_cleanup()
            self._process_reservations[proc] = reservation
            closing = self._register_process(session_id, proc)
            if closing:
                await self._observe_process_release(session_id, proc, reservation)
                raise ApplicationStoppingError("Subprocess created while application was stopping")
            return proc

        task = asyncio.create_task(spawn(), name="subprocess-create")
        with self._procs_lock:
            self._spawning.add(task)
            self._idle.clear()
        task.add_done_callback(self._spawn_finished)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError as cancelled:
            try:
                proc = await asyncio.shield(task)
                reservation = self._process_reservations[proc]
                await self._observe_process_release(session_id, proc, reservation)
            except ApplicationStoppingError:
                pass
            except BaseException as cleanup_error:
                self._record_cleanup_failure(cleanup_error)
                raise BaseExceptionGroup(
                    "Subprocess creation cancellation failed", [cancelled, cleanup_error]
                ) from None
            raise

    def _spawn_finished(self, task: asyncio.Task[asyncio.subprocess.Process]) -> None:
        if not task.cancelled():
            task.exception()  # 创建失败也由等待该任务的调用方取得；不能遗留未观察异常。
        with self._procs_lock:
            self._spawning.remove(task)
            if not self._operations and not self._active_procs and not self._spawning:
                self._idle.set()

    @contextmanager
    def _sync_process(
        self,
        args: list[str],
        popen_kwargs: dict,
        session_id: str
        ) -> Iterator[subprocess.Popen]:
        operation = self._begin_operation()
        proc: subprocess.Popen | None = None
        try:
            proc = subprocess.Popen(args, **popen_kwargs)
            reservation = self._reserve_cleanup()
            self._process_reservations[proc] = reservation
            if self._register_process(session_id, proc):
                raise ApplicationStoppingError("Subprocess created while application was stopping")
            yield proc
        finally:
            original = sys.exception()
            try:
                if proc is not None:
                    reservation = self._process_reservations[proc]
                    asyncio.get_running_loop().create_task(
                        self._observe_process_release(session_id, proc, reservation)
                    )
            except BaseException as cleanup_error:
                self._record_cleanup_failure(cleanup_error)
                if original is not None:
                    raise BaseExceptionGroup("Subprocess cleanup failed", [original, cleanup_error]) from None
                raise
            finally:
                if proc is not None and proc.poll() is not None:
                    self._forget_process(session_id, proc)
                self._finish_operation(operation)

    @asynccontextmanager
    async def _async_process(
        self,
        args: list[str],
        popen_kwargs: dict,
        session_id: str
        ) -> AsyncIterator[asyncio.subprocess.Process]:
        operation = self._begin_operation()
        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await self._spawn_async(args, popen_kwargs, session_id)
            yield proc
        finally:
            original = sys.exception()
            try:
                if proc is not None:
                    reservation = self._process_reservations[proc]
                    await self._observe_process_release(session_id, proc, reservation)
            except BaseException as cleanup_error:
                self._record_cleanup_failure(cleanup_error)
                if original is not None:
                    raise BaseExceptionGroup("Subprocess cleanup failed", [original, cleanup_error]) from None
                raise
            finally:
                if proc is not None and proc.returncode is not None:
                    self._forget_process(session_id, proc)
                self._finish_operation(operation)

    # -- 同步入口（任意线程） ----------------------------------------------- #

    def run(
        self,
        args: list[str],
        *,
        cwd: str,
        timeout: float | None = None,
        extra_env: dict[str, str] | None = None,
        session_id: str = ""
        ) -> subprocess.CompletedProcess[str]:
        """以沙盒化工作目录运行子进程（同步阻塞）。

        *args* — 命令 + 参数（调用方已做命名空间路径检查）。
        *cwd* — 已解析的绝对路径字符串（由 Sandbox.resolve 产出）。
        *timeout* — 超时秒数（调用方已注入默认值）。
        *session_id* — 发起会话 ID，用于中断路径按会话终止活动进程。
        """
        if not args:
            raise ValueError("subprocess args must not be empty")

        env = build_subprocess_env(extra_env)

        logger.debug("SubprocessRunner.run | cwd=%s cmd=%s", cwd, args)

        # 操作在创建进程前登记；同步创建和 communicate 都受关闭所有权覆盖。
        popen_kwargs: dict = {
            "cwd": cwd,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": False,
            "env": env,
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = windows_process_group_flags()
        with self._sync_process(args, popen_kwargs, session_id) as proc:
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                raise subprocess.TimeoutExpired(
                    cmd=args[0], timeout=timeout if timeout is not None else 0,
                    output="", stderr="",
                ) from exc
            return completed_process_from_bytes(
                args=args, returncode=proc.returncode, stdout=stdout, stderr=stderr,
            )

    # -- 真异步入口（事件循环内 await） ------------------------------------- #

    async def run_async(
        self,
        args: list[str],
        *,
        cwd: str,
        timeout: float | None = None,
        extra_env: dict[str, str] | None = None,
        session_id: str = ""
        ) -> subprocess.CompletedProcess[str]:
        """以沙盒化工作目录运行子进程（真异步，事件循环不阻塞）。

        与 ``run()`` 语义相同，但使用 ``asyncio.create_subprocess_exec`` +
        ``await proc.communicate()``，子进程等待为协程挂起而非线程阻塞，
        事件循环保持响应（流式推送、gateway 请求、消息队列入队等不受影响）。

        取消语义（自清理 + kill_active 兜底双保险）：
        - ``CancelledError`` → 杀树 + 限量 wait → 原样 re-raise（保 ToolExecutor
          的 ``ToolInterrupted("dispatch")`` 转换语义）。
        - 超时 → 杀树 + 限量 wait → 抛 ``subprocess.TimeoutExpired``（与同步版
          异常类型对齐，工具 ``except`` 分支零改动）。
        """
        if not args:
            raise ValueError("subprocess args must not be empty")

        env = build_subprocess_env(extra_env)

        logger.debug("SubprocessRunner.run_async | cwd=%s cmd=%s", cwd, args)

        popen_kwargs: dict = {
            "cwd": cwd,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "env": env,
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = windows_process_group_flags()
        async with self._async_process(args, popen_kwargs, session_id) as proc:
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
            except asyncio.TimeoutError as exc:
                raise subprocess.TimeoutExpired(
                    cmd=args[0], timeout=timeout if timeout is not None else 0,
                    output="", stderr="",
                ) from exc
            return completed_process_from_bytes(
                args=args, returncode=proc.returncode, stdout=stdout, stderr=stderr,
            )

    async def run_async_line_processor(
        self,
        args: list[str],
        *,
        cwd: str,
        on_stdout_line: Callable[[bytes], bool],
        timeout: float | None = None,
        extra_env: dict[str, str] | None = None,
        session_id: str = "",
        stderr_byte_limit: int = SEARCH_PROCESS_STDERR_MAX_BYTES
        ) -> ProcessLineStreamResult:
        """以逐行 stdout 回调方式运行子进程，并允许调用方提前终止。

        ``on_stdout_line`` 返回 ``False`` 时表示调用方已取得足够输出，
        本方法终止整棵进程树并返回 ``truncated=True``。stderr 独立并发
        读取，并按字节上限保留，避免子进程阻塞或错误输出无限增长。
        """
        if not args:
            raise ValueError("subprocess args must not be empty")

        env = build_subprocess_env(extra_env)
        logger.debug("SubprocessRunner.run_async_line_processor | cwd=%s cmd=%s", cwd, args)

        popen_kwargs: dict = {
            "cwd": cwd,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "env": env,
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = windows_process_group_flags()

        async with self._async_process(args, popen_kwargs, session_id) as proc:
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
                    stdout_line_count += 1
                    if not on_stdout_line(line):
                        truncated = True
                        await asyncio.to_thread(_kill_proc_tree, proc.pid)
                        return

            stderr_task = asyncio.create_task(read_stderr(), name="subprocess-stderr")
            stdout_task = asyncio.create_task(read_stdout(), name="subprocess-stdout")
            try:
                await asyncio.wait_for(stdout_task, timeout=timeout)
                await asyncio.wait_for(
                    proc.wait(),
                    SUBPROCESS_SOFT_CLEANUP_WAIT_TIME if truncated else timeout,
                )
                await asyncio.wait_for(stderr_task, SUBPROCESS_SOFT_CLEANUP_WAIT_TIME)
            except asyncio.TimeoutError as exc:
                raise subprocess.TimeoutExpired(
                    cmd=args[0], timeout=timeout if timeout is not None else 0,
                    output="", stderr="",
                ) from exc
            finally:
                original = sys.exception()
                for task in (stdout_task, stderr_task):
                    if not task.done():
                        task.cancel()
                results = await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
                failures = [
                    result for result in results
                    if isinstance(result, BaseException)
                    and not isinstance(result, asyncio.CancelledError)
                    and result is not original
                ]
                if failures:
                    if original is not None:
                        failures.insert(0, original)
                    raise BaseExceptionGroup("Subprocess output processing failed", failures)

            stderr_text = safe_decode(b"".join(stderr_chunks))
            if stderr_truncated:
                stderr_text += "\n[stderr truncated]"
            return ProcessLineStreamResult(
                returncode=proc.returncode,
                stderr=stderr_text,
                truncated=truncated,
                stdout_line_count=stdout_line_count,
            )

    # -- 中断终止 ---------------------------------------------------------- #

    def kill_active(self, session_id: str) -> None:
        """请求终止匹配会话的进程树；空会话 ID 表示全部。

        此同步入口不提前移除登记。进程的等待及管道回收由原 run 操作
        完成，应用关闭再通过 terminate_all/wait_idle 确认真实退出。
        """
        with self._procs_lock:
            if session_id:
                processes = list(self._active_procs.get(session_id, ()))
            else:
                processes = [proc for bucket in self._active_procs.values() for proc in bucket]
        for proc in processes:
            alive = proc.poll() is None if isinstance(proc, subprocess.Popen) else proc.returncode is None
            reservation = self._process_reservations.get(proc)
            if not alive or reservation is None or proc in self._process_handles:
                continue
            identity = (
                OwnedProcessIdentity.from_popen(proc)
                if isinstance(proc, subprocess.Popen)
                else OwnedProcessIdentity.from_asyncio(proc)
            )

            async def release(
                target: subprocess.Popen | asyncio.subprocess.Process = proc,
                owned: OwnedProcessIdentity | None = identity,
            ) -> None:
                if owned is not None and not self._process_released(target):
                    await terminate_owned_tree(owned)
                if isinstance(target, subprocess.Popen):
                    await asyncio.to_thread(target.wait)
                else:
                    await target.wait()

            self.runtime.cleanup.begin_threadsafe(
                reservation,
                resource_id=self._process_key(proc),
                phase="terminate",
                factory=release,
                is_released=lambda target=proc: self._process_released(target),
                kill_authorized=identity is not None,
            )

    async def virtual_shotdown(self) -> None:
        """关闭：先禁止新进程，再终止所有活动进程并等待真正退出。

        错误直接上抛；不吞掉清理失败或覆盖为成功。
        """
        await close_resources((self.terminate_all, self.wait_idle))