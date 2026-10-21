"""SDK-compatible stdio framing with explicit process and task ownership."""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import IO, Any

import anyio
from anyio.abc import Process
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from anyio.streams.text import TextReceiveStream
from pydantic import ValidationError

# SDK stdio_client只暴露流，不暴露进程。仅此兼容边界复用其平台创建/杀树
# 实现和消息类型；版本缺少这些接口直接失败，不修改SDK或扫描宿主PID。
from mcp.client.stdio import (
    StdioServerParameters,
    _create_platform_compatible_process,
    _get_executable_command,
    get_default_environment,
)
from mcp.os.win32.utilities import FallbackProcess
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage

from entity.constant import (
    MCP_STDIO_PROCESS_TERMINATION_TIMEOUT,
    MCP_STDIO_STDIN_CLOSE_TIMEOUT,
    SYSTEM_QUIESCE_TIMEOUT_SECONDS,
)
from system.lifecycle import LifecycleFailure


class MCPStdioTransport:
    def __init__(
        self,
        params: StdioServerParameters,
        errlog: IO[str],
        on_failure: Callable[[BaseException], None]
        ) -> None:
        self._params = params
        self._errlog = errlog
        self._on_failure = on_failure
        self._process: Process | FallbackProcess | None = None
        self._job: Any = None
        self._create_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._io_tasks: list[asyncio.Task[None]] = []
        self._streams: list[MemoryObjectReceiveStream[Any] | MemoryObjectSendStream[Any]] = []
        self._opened = False
        self._inside_open = False
        self._closing = False
        self._creation_error_delivered = False

    def _require_config(self) -> dict[str, Any]:
        for key in ("command", "args"):
            value = getattr(self._params, key)
            if value is None:
                raise LifecycleFailure(f"MCP stdio parameter is required: {key}")
            return value
        raise LifecycleFailure("unreachable")

    async def _create(self) -> None:
        self._process = await _create_platform_compatible_process(
            command=_get_executable_command(self._require_config()),
            args=self._params.args,
            env={**get_default_environment(), **(self._params.env or {})},
            errlog=self._errlog,
            cwd=self._params.cwd,
        )
        if os.name == "nt":
            # SDK仅动态附加_job_object，没有公开查询API；此处是必要的外部兼容边界。
            # SDK可能静默放弃Job绑定；无法持有子树时拒绝启动，而非假称完整杀树。
            job = getattr(self._process, "_job_object", None)
            if job is None:
                process = self._process
                self._process = None
                if process is not None:
                    process.kill()
                    try:
                        await process.wait()
                    except BaseException:
                        pass
                    async with process:
                        pass
                raise LifecycleFailure("MCP SDK did not provide ownership of the Windows process job")
            self._job = job

    async def _terminate_owned_tree(self, process: Process | FallbackProcess) -> None:
        if os.name == "nt":
            import win32api
            import win32job

            if self._job is None:
                # 仅失败创建的部分资源清理；调用方仍保留上述启动失败。
                process.kill()
                return
            win32job.TerminateJobObject(self._job, 1)
            async with asyncio.timeout(SYSTEM_QUIESCE_TIMEOUT_SECONDS):
                while win32job.QueryInformationJobObject(
                    self._job, win32job.JobObjectBasicAccountingInformation,
                )["ActiveProcesses"]:
                    await asyncio.sleep(0.01)
            win32api.CloseHandle(self._job)
            self._job = None
            return
        # SDK创建POSIX进程时使用start_new_session=True；进程组身份来自真实句柄，
        # 不查询宿主子进程，也不使用Windows危险的os.kill(pid, 0)。
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = asyncio.get_running_loop().time() + MCP_STDIO_PROCESS_TERMINATION_TIMEOUT
        while asyncio.get_running_loop().time() < deadline:
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                return
            await asyncio.sleep(0.01)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        async with asyncio.timeout(SYSTEM_QUIESCE_TIMEOUT_SECONDS):
            while True:
                try:
                    os.killpg(process.pid, 0)
                except ProcessLookupError:
                    return
                await asyncio.sleep(0.01)

    @staticmethod
    def _observe_creation(task: asyncio.Task[None]) -> None:
        # 原始连接等待方或清理任务处理结局；这里只观察以免取消窗口丢失异常。
        if not task.cancelled():
            task.exception()

    @asynccontextmanager
    async def open(self) -> AsyncIterator[tuple[MemoryObjectReceiveStream[Any], MemoryObjectSendStream[Any]]]:
        if self._opened:
            raise LifecycleFailure("MCP stdio transport cannot be opened twice")
        self._opened = True
        self._inside_open = True
        read_writer, read_stream = anyio.create_memory_object_stream[SessionMessage | Exception](0)
        write_stream, write_reader = anyio.create_memory_object_stream[SessionMessage](0)
        self._streams = [read_writer, read_stream, write_stream, write_reader]
        self._create_task = asyncio.create_task(self._create(), name="mcp-stdio-create")
        self._create_task.add_done_callback(self._observe_creation)
        try:
            try:
                await asyncio.shield(self._create_task)
            except BaseException as original:
                self._creation_error_delivered = (
                    self._create_task.done() and not self._create_task.cancelled()
                    and self._create_task.exception() is original
                )
                await self._cleanup_after_error(original)
                raise
            process = self._process
            if process is None:
                raise LifecycleFailure("MCP stdio process was not published by its creator")

            async def read_stdout() -> None:
                if process.stdout is None:
                    raise LifecycleFailure("MCP process has no stdout pipe")
                try:
                    async with read_writer:
                        buffer = ""
                        async for chunk in TextReceiveStream(
                            process.stdout, encoding=self._params.encoding,
                            errors=self._params.encoding_error_handler,
                        ):
                            lines = (buffer + chunk).split("\n")
                            buffer = lines.pop()
                            for line in lines:
                                try:
                                    message = JSONRPCMessage.model_validate_json(line)
                                except ValidationError as error:
                                    await read_writer.send(error)
                                else:
                                    await read_writer.send(SessionMessage(message))
                except (anyio.ClosedResourceError, anyio.BrokenResourceError):
                    if not self._closing:
                        raise

            async def write_stdin() -> None:
                if process.stdin is None:
                    raise LifecycleFailure("MCP process has no stdin pipe")
                try:
                    async with write_reader:
                        async for message in write_reader:
                            text = message.message.model_dump_json(by_alias=True, exclude_none=True)
                            await process.stdin.send((text + "\n").encode(
                                self._params.encoding, self._params.encoding_error_handler,
                            ))
                except (anyio.ClosedResourceError, anyio.BrokenResourceError):
                    if not self._closing:
                        raise

            # 传输上下文始终由同一个MCPServerTask进入/退出；SDK ClientSession的
            # AnyIO取消作用域也保持原任务。I/O子任务结构化管理，不跨任务退出作用域。
            async with asyncio.TaskGroup() as group:
                self._io_tasks = [
                    group.create_task(read_stdout(), name="mcp-stdio-reader"),
                    group.create_task(write_stdin(), name="mcp-stdio-writer"),
                ]
                try:
                    yield read_stream, write_stream
                except BaseException as original:
                    await self._cleanup_after_error(original)
                    raise
                else:
                    await self._wait_cleanup()
                finally:
                    for task in self._io_tasks:
                        task.cancel()
        finally:
            self._inside_open = False

    async def _cleanup_after_error(self, original: BaseException) -> None:
        try:
            await self._wait_cleanup()
        except BaseException as cleanup:
            raise BaseExceptionGroup("MCP stdio operation and cleanup failed", [original, cleanup])

    async def _wait_cleanup(self) -> None:
        self._closing = True
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._cleanup(), name="mcp-stdio-cleanup")
            self._close_task.add_done_callback(self._observe_cleanup)
        # 屏蔽SDK的外层AnyIO取消；重复asyncio取消仍可交回上层，真实清理task保留。
        with anyio.CancelScope(shield=True):
            done, _ = await asyncio.wait({self._close_task}, timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS)
        if not done:
            failure = LifecycleFailure("MCP stdio cleanup is still active")
            self._on_failure(failure)
            raise failure
        self._close_task.result()

    async def _cleanup(self) -> None:
        errors: list[BaseException] = []
        creator = self._create_task
        if creator is not None:
            # 实际创建task绝不取消；晚创建的进程仍在本任务内取得和释放。
            try:
                await asyncio.shield(creator)
            except BaseException as error:
                if not self._creation_error_delivered:
                    errors.append(error)
        process = self._process
        if process is not None:
            if process.stdin is not None:
                try:
                    with anyio.fail_after(MCP_STDIO_STDIN_CLOSE_TIMEOUT):
                        await process.stdin.aclose()
                except BaseException as error:
                    errors.append(error)
            try:
                with anyio.fail_after(MCP_STDIO_PROCESS_TERMINATION_TIMEOUT):
                    await process.wait()
            except TimeoutError:
                pass  # 明确优雅退出窗口用尽，下面执行SDK平台杀树。
            except BaseException as error:
                errors.append(error)
            try:
                # 即便父进程已自然退出也释放SDK Windows Job/剩余同组进程。
                await self._terminate_owned_tree(process)
                with anyio.fail_after(MCP_STDIO_PROCESS_TERMINATION_TIMEOUT):
                    await process.wait()
                async with process:
                    pass
            except BaseException as error:
                errors.append(error)
            else:
                self._process = None
        for stream in tuple(self._streams):
            try:
                await stream.aclose()
            except BaseException as error:
                errors.append(error)
            else:
                self._streams.remove(stream)
        if errors:
            failure = LifecycleFailure("MCP stdio resource release failed")
            failure.__cause__ = BaseExceptionGroup("MCP stdio cleanup errors", errors)
            raise failure

    def _observe_cleanup(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            self._on_failure(LifecycleFailure("MCP stdio cleanup task was cancelled"))
        elif (error := task.exception()) is not None:
            self._on_failure(error)

    async def aclose(self) -> None:
        if self._inside_open:
            raise LifecycleFailure("MCP stdio owner must exit before external cleanup")
        await self._wait_cleanup()

    @property
    def is_idle(self) -> bool:
        return (
            not self._inside_open and self._process is None and self._job is None and not self._streams
            and (self._create_task is None or self._create_task.done())
            and (self._close_task is None or self._close_task.done())
            and all(task.done() for task in self._io_tasks)
        )

    @property
    def process_pid(self) -> int | None:
        return None if self._process is None else self._process.pid
