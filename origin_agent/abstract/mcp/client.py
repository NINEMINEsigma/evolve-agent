#!/usr/bin/env python3
"""
MCP (Model Context Protocol) Client Support

Connects to external MCP servers via stdio, HTTP/StreamableHTTP, or SSE
transport, discovers their tools, and registers them into the evolve-agent
tool registry so the agent can call them like any built-in tool.

Configuration is loaded by MCPSystem and passed explicitly to its MCPCore.
The ``mcp`` package is optional only when no enabled server is configured;
enabled capabilities fail startup if the required SDK is unavailable.

Example config::

    mcp_servers:
      filesystem:
        command: "npx"
        args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        env: {}
        timeout: 120         # per-tool-call timeout in seconds (default: 120)
        connect_timeout: 60  # initial connection timeout (default: 60)
      github:
        command: "npx"
        args: ["-y", "@modelcontextprotocol/server-github"]
        env:
          GITHUB_PERSONAL_ACCESS_TOKEN: "ghp_..."
        supports_parallel_tool_calls: true  # tools from this server may run concurrently
      remote_api:
        url: "https://my-mcp-server.example.com/mcp"
        headers:
          Authorization: "Bearer sk-..."
        timeout: 180
      searxng:
        url: "http://localhost:8000/sse"
        transport: sse       # use SSE transport instead of Streamable HTTP
        timeout: 180
        connect_timeout: 10
        command: "npx"
        args: ["-y", "analysis-server"]
        sampling:                    # server-initiated LLM requests
          enabled: true              # default: true
          model: "gemini-3-flash"    # override model (optional)
          max_tokens_cap: 4096       # max tokens per request
          timeout: 30                # LLM call timeout (seconds)
          max_rpm: 10                # max requests per minute
          allowed_models: []         # model whitelist (empty = all)
          max_tool_rounds: 5         # tool loop limit (0 = disable)
          log_level: "info"          # audit verbosity

Features:
    - Stdio transport (command + args) and HTTP/StreamableHTTP transport (url)
    - SSE transport (transport: sse) for MCP servers using the SSE protocol
    - Automatic reconnection with exponential backoff (up to 5 retries)
    - Environment variable filtering for stdio subprocesses (security)
    - Credential stripping in error messages returned to the LLM
    - Configurable per-server timeouts for tool calls and connections
    - Thread-safe architecture with dedicated background event loop
    - Sampling support: MCP servers can request LLM completions via
      sampling/createMessage (text and tool-use responses)
    - Parallel tool call opt-in: per-server ``supports_parallel_tool_calls``
      flag allows concurrent execution of tools from the same server

Architecture:
    Each MCPCore owns one dedicated background event loop in a daemon thread.
    Each MCP server runs as a long-lived asyncio Task on that loop, keeping
    its transport context alive. Tool call coroutines are scheduled onto the
    owning loop via ``run_coroutine_threadsafe()``.

    On shutdown, each server Task is signalled to exit its ``async with``
    block, ensuring the anyio cancel-scope cleanup happens in the *same*
    Task that opened the connection (required by anyio).

Thread safety:
    A Core lock protects its servers, loop/thread references, child PIDs,
    circuit-breaker state and stderr handle. Multiple Application instances
    do not share MCP runtime state.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Iterator
from contextlib import contextmanager
import inspect
import json
import logging
import os
import re
import shutil
import sys
import threading
import time
from datetime import datetime
from typing import IO, Any, Callable, Coroutine, TYPE_CHECKING

from urllib.parse import urlparse

from system.convert import as_bool
from system.lifecycle import (
    ApplicationStoppingError, LifecycleFailure, TaskOwner,
    close_resources, requires_lifecycle_propagation,
)
from entity.constant import (
    ApplicationState, SYSTEM_QUIESCE_TIMEOUT_SECONDS,
    MCP_CIRCUIT_BREAKER_THRESHOLD, MCP_CIRCUIT_BREAKER_COOLDOWN_SECONDS,
    MCP_BRIDGE_TIMEOUT_SECONDS, MCP_CLEANUP_TIMEOUT_SECONDS,
    MCP_TOOL_TIMEOUT_SECONDS as _DEFAULT_TOOL_TIMEOUT,
    MCP_CONNECT_TIMEOUT_SECONDS as _DEFAULT_CONNECT_TIMEOUT,
    MCP_SSE_READ_TIMEOUT_SECONDS as _SSE_READ_TIMEOUT,
    MCP_MAX_BACKOFF_SECONDS as _MAX_BACKOFF_SECONDS,
    MCP_MAX_RECONNECT_RETRIES as _MAX_RECONNECT_RETRIES,
    MCP_MAX_INITIAL_CONNECT_RETRIES as _MAX_INITIAL_CONNECT_RETRIES,
    TOOL_INTERNAL_ARG_KEYS,
)
from entity.puretype import MCPBridgeCall, Role
from .work import MCPThreadWork
from .schema import normalize_mcp_input_schema as _normalize_schema

if TYPE_CHECKING:
    from mcp import ClientSession
    from abstract.tools.registry import ToolRegistry
    from system.context import RuntimeContext
    from system.runtime import RuntimeSystem
    from .oauth_manager import MCPOAuthManager
    from .stdio import MCPStdioTransport
    from mcp.types import InitializeResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Callback-based registry for tool registration (replacement for
# the project's ToolRegistry)
# ---------------------------------------------------------------------------


class MCPCore:
    """Own MCP-loop tasks and cross-thread handoffs for one Application."""

    def __init__(self, ctx: RuntimeContext, registry: ToolRegistry, runtime: RuntimeSystem) -> None:
        self.context = ctx
        self.registry = registry
        self.runtime = runtime
        self.lock = threading.RLock()
        self.servers: dict[str, MCPServerTask] = {}
        self.server_error_counts: dict[str, int] = {}
        self.server_breaker_opened_at: dict[str, float] = {}
        self.mcp_loop: asyncio.AbstractEventLoop | None = None
        self.mcp_thread: threading.Thread | None = None
        self.stderr_log_fh: IO[str] | None = None
        self.stderr_log_lock = threading.Lock()
        self.closed = False
        self._started = threading.Event()
        self._thread_error: BaseException | None = None
        self._calls: dict[concurrent.futures.Future[Any], MCPBridgeCall] = {}
        self._control_futures: list[concurrent.futures.Future[Any]] = []
        self._stop_task: asyncio.Task[None] | None = None
        self._shutdown_task: asyncio.Task[None] | None = None
        self._loop_resources_closed = False
        self._owner: TaskOwner | None = None
        self._oauth_manager: MCPOAuthManager | None = None
        self._native: MCPThreadWork | None = None
        self._management_lock: asyncio.Lock | None = None

    @property
    def oauth_manager(self) -> MCPOAuthManager:
        if self._oauth_manager is None:
            raise LifecycleFailure("MCP OAuth manager is not initialized")
        return self._oauth_manager

    @property
    def owner(self) -> TaskOwner:
        if self._owner is None:
            raise LifecycleFailure("MCP request owner is not initialized")
        return self._owner

    @property
    def native(self) -> MCPThreadWork:
        if self._native is None:
            raise LifecycleFailure("MCP native executor is not initialized")
        return self._native

    @contextmanager
    def admission(self) -> Iterator[None]:
        with self.runtime.admission():
            with self.lock:
                if self.closed:
                    raise ApplicationStoppingError("MCP admission is closed")
                yield

    @contextmanager
    def setup_admission(self) -> Iterator[None]:
        state = self.runtime.state
        with self.lock:
            if self.closed or state not in (ApplicationState.STARTING, ApplicationState.RUNNING):
                raise ApplicationStoppingError("MCP setup admission is closed")
            yield

    def close_admission(self) -> None:
        # 此入口可从主loop调用；不跨loop直接操作TaskOwner或asyncio.Event。
        with self.lock:
            self.closed = True

    def ensure_loop(self) -> None:
        with self.setup_admission():
            if self.mcp_thread is None:
                loop = asyncio.new_event_loop()
                self.mcp_loop = loop
                self.mcp_thread = threading.Thread(target=self._run_loop, name="mcp-event-loop", daemon=True)
                try:
                    self.mcp_thread.start()
                except BaseException:
                    if self.mcp_thread.ident is None:
                        loop.close()
                        self.mcp_loop = None
                        self.mcp_thread = None
                    raise
        if not self._started.wait(SYSTEM_QUIESCE_TIMEOUT_SECONDS):
            raise LifecycleFailure("MCP event loop did not start")
        if self._thread_error is not None:
            raise self._thread_error

    def _run_loop(self) -> None:
        from .oauth_manager import MCPOAuthManager

        loop = self.mcp_loop
        if loop is None:
            raise LifecycleFailure("MCP event loop was not assigned")
        asyncio.set_event_loop(loop)

        def initialize() -> None:
            try:
                self._owner = TaskOwner("mcp-management", self.runtime.record_failure)
                self._management_lock = asyncio.Lock()
                self._oauth_manager = MCPOAuthManager(self.context.agentspace / "mcp-tokens")
                self._native = MCPThreadWork("mcp-sampling", self.runtime.record_failure)
                self._native.start()
            except BaseException as error:
                self._thread_error = error
                self.runtime.record_failure(error)
            finally:
                self._started.set()

        loop.set_exception_handler(self._loop_exception)
        loop.call_soon(initialize)
        try:
            loop.run_forever()
        except BaseException as error:
            self._thread_error = error
            self.runtime.record_failure(error)
        finally:
            self._started.set()

    def _loop_exception(self, loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        error = context.get("exception")
        if error is None:
            error = LifecycleFailure(context.get("message", "MCP event loop failure"))
        self.runtime.record_failure(error)
        loop.default_exception_handler(context)

    def call(
        self, factory: Callable[[], Coroutine[Any, Any, Any]], *,
        timeout: float, startup: bool = False,
        owner: TaskOwner | None = None, admission: Callable | None = None,
    ) -> Any:
        # 同步工具handler/系统工作线程使用此入口，绝不能阻塞任一事件循环。
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise LifecycleFailure("Synchronous MCP bridge cannot block an event loop")
        admit = admission or (self.setup_admission if startup else self.admission)
        with admit():
            loop = self.mcp_loop
            if loop is None or not loop.is_running():
                raise LifecycleFailure("MCP event loop is unavailable")
            record = MCPBridgeCall()
            self._calls[record.result] = record
            loop.call_soon_threadsafe(self._start_call, record, factory, admit, owner)
        try:
            try:
                return record.result.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                if record.result.done():
                    return record.result.result()
                with self.lock:
                    record.cancel_requested = True
                loop.call_soon_threadsafe(self._cancel_call, record)
                raise TimeoutError(f"MCP call timed out after {timeout}s")
        finally:
            with self.lock:
                record.request_released = True
                if record.result.done():
                    self._calls.pop(record.result, None)

    def _start_call(self, record: MCPBridgeCall, factory: Callable, admit: Callable, owner: TaskOwner | None) -> None:
        gate = asyncio.get_running_loop().create_future()

        async def invoke() -> Any:
            await gate
            request_owner = self.owner if owner is None else owner
            return await request_owner.run_request(factory, name="mcp-call", admission=admit)

        with self.lock:
            cancelled = record.cancel_requested
        if cancelled:
            record.result.set_exception(ApplicationStoppingError("MCP request was cancelled before startup"))
            with self.lock:
                if record.request_released:
                    self._calls.pop(record.result, None)
            return
        wrapper = invoke()
        try:
            task = asyncio.create_task(wrapper, name="mcp-bridge-waiter")
        except BaseException as error:
            wrapper.close()
            record.result.set_exception(error)
            with self.lock:
                if record.request_released:
                    self._calls.pop(record.result, None)
            return
        with self.lock:
            record.task = task
        task.add_done_callback(lambda done: self._finish_call(record, done))
        gate.set_result(None)
        if record.cancel_requested:
            self._cancel_call(record)

    def _cancel_call(self, record: MCPBridgeCall) -> None:
        with self.lock:
            task = record.task
            if task is not None and not task.done() and not record.cancel_sent:
                record.cancel_sent = True
                task.cancel()

    def _finish_call(self, record: MCPBridgeCall, task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            error: BaseException | None = ApplicationStoppingError("MCP request was cancelled by its owner")
            value = None
        else:
            error = task.exception()
            value = None if error is not None else task.result()
        with self.lock:
            abandoned = record.cancel_sent
            if error is None:
                record.result.set_result(value)
            else:
                record.result.set_exception(error)
            if record.request_released:
                self._calls.pop(record.result, None)
        if abandoned and error is not None and not isinstance(
            error, (concurrent.futures.CancelledError, ApplicationStoppingError)
        ):
            self.runtime.record_failure(error)

    def register(self, servers: dict[str, dict]) -> list[str]:
        self.ensure_loop()
        return self.call(lambda: self._register(servers), timeout=MCP_BRIDGE_TIMEOUT_SECONDS, startup=True)

    async def _register(self, servers: dict[str, dict]) -> list[str]:
        lock = self._management_lock
        if lock is None:
            raise LifecycleFailure("MCP management lock is unavailable")
        async with lock:
            with self.setup_admission():
                pass
            async with asyncio.TaskGroup() as group:
                for name, config in servers.items():
                    if config.get("enabled", True) and name not in self.servers:
                        group.create_task(_discover_and_register_server(name, config, self))
            return _existing_tool_names(self)

    def refresh(self, servers: dict[str, dict]) -> dict[str, Any]:
        self.ensure_loop()
        return self.call(lambda: self._refresh(servers), timeout=MCP_BRIDGE_TIMEOUT_SECONDS)

    async def _refresh(self, config: dict[str, dict]) -> dict[str, Any]:
        lock = self._management_lock
        if lock is None:
            raise LifecycleFailure("MCP management lock is unavailable")
        async with lock:
            with self.admission():
                pass
            enabled = {name: value for name, value in config.items() if value.get("enabled", True)}
            removed: list[str] = []
            added: list[str] = []
            failed: list[str] = []
            for name in tuple(self.servers):
                if name not in enabled:
                    await self.servers[name].shutdown()
                    with self.lock:
                        del self.servers[name]
                    removed.append(name)
            for name, value in enabled.items():
                with self.admission():
                    pass
                if name in self.servers:
                    _reset_server_error(self, name)
                    continue
                try:
                    await _discover_and_register_server(name, value, self)
                except Exception as error:
                    if requires_lifecycle_propagation(error):
                        raise
                    server = self.servers.get(name)
                    if server is not None:
                        await server.shutdown()
                        with self.lock:
                            del self.servers[name]
                    # 仅明确外部连接失败保留运行期failed结果；配置/逻辑错误传播。
                    if not _is_retryable_transport_error(error) and not _is_auth_error(error):
                        raise
                    failed.append(name)
                else:
                    added.append(name)
                    _reset_server_error(self, name)
            return {"refreshed": True, "removed": removed, "added": added,
                    "failed": failed, "status": self.status()}

    def status(self) -> list[dict[str, Any]]:
        return get_mcp_status(self)

    def _control(self, factory: Callable[[], Coroutine[Any, Any, None]]) -> None:
        loop = self.mcp_loop
        if loop is None:
            return
        if not loop.is_running():
            if self._thread_error is not None:
                raise self._thread_error
            raise LifecycleFailure("MCP event loop stopped before cleanup")
        future = asyncio.run_coroutine_threadsafe(factory(), loop)
        with self.lock:
            self._control_futures.append(future)
        future.add_done_callback(self._release_control)
        try:
            future.result(timeout=MCP_CLEANUP_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError:
            if future.done():
                future.result()
            raise LifecycleFailure("MCP cleanup is still running on its dedicated loop")

    def _release_control(self, future: concurrent.futures.Future[Any]) -> None:
        with self.lock:
            self._control_futures.remove(future)
        # 清理失败由独立cleanup task观察并报告，Future不得无人观察。
        if not future.cancelled():
            future.exception()

    async def _stop_once(self) -> None:
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._stop_calls(), name="mcp-stop-calls")
            self._stop_task.add_done_callback(self._observe_cleanup)
        await asyncio.shield(self._stop_task)

    def stop_calls(self) -> None:
        self.close_admission()
        self._control(self._stop_once)

    def _observe_cleanup(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            self.runtime.record_failure(LifecycleFailure("MCP cleanup task was cancelled"))
        elif (error := task.exception()) is not None:
            self.runtime.record_failure(error)

    async def _stop_calls(self) -> None:
        if self._oauth_manager is not None:
            self._oauth_manager.close_admission()
        actions = []
        if self._owner is not None:
            actions.append(lambda: self.owner.cancel_and_wait(timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS))
        actions.extend(server.stop_calls for server in tuple(self.servers.values()))
        if self._native is not None:
            actions.append(self._native.close)
        await close_resources(actions)

    async def _close_loop_resources(self) -> None:
        errors: list[BaseException] = []
        actions = [self._stop_once]
        actions.extend(server.shutdown for server in tuple(self.servers.values()))
        if self._oauth_manager is not None:
            actions.append(self._oauth_manager.aclose)
        for action in actions:
            try:
                await action()
            except BaseException as error:
                errors.append(error)
        # 失败历史可以传播但已退出资源仍须释放；活任务绝不通过清表伪装退出。
        deadline = asyncio.get_running_loop().time() + SYSTEM_QUIESCE_TIMEOUT_SECONDS
        while True:
            with self.lock:
                calls_idle = not self._calls
            if calls_idle or asyncio.get_running_loop().time() >= deadline:
                break
            await asyncio.sleep(0.01)
        if (
            calls_idle
            and (self._owner is None or self._owner.is_idle)
            and (self._native is None or self._native.is_idle)
            and (self._oauth_manager is None or self._oauth_manager.is_idle)
            and all(server.is_idle for server in self.servers.values())
        ):
            await asyncio.get_running_loop().shutdown_asyncgens()
            await asyncio.get_running_loop().shutdown_default_executor()
            self._loop_resources_closed = True
        else:
            errors.append(LifecycleFailure("MCP resources remain owned after shutdown"))
        if errors:
            raise BaseExceptionGroup("MCP shutdown failed", errors)

    async def _shutdown_once(self) -> None:
        if self._shutdown_task is None:
            self._shutdown_task = asyncio.create_task(self._close_loop_resources(), name="mcp-close-resources")
            self._shutdown_task.add_done_callback(self._observe_cleanup)
        await asyncio.shield(self._shutdown_task)

    def shutdown(self) -> None:
        self.close_admission()
        errors: list[BaseException] = []
        if self.mcp_loop is not None:
            try:
                self._control(self._shutdown_once)
            except BaseException as error:
                errors.append(error)
            if self._loop_resources_closed:
                try:
                    _stop_mcp_loop(self)
                except BaseException as error:
                    errors.append(error)
        if self.mcp_loop is None:
            self.close_stderr_log()
            with self.lock:
                self.servers.clear()
        if errors:
            raise BaseExceptionGroup("MCP shutdown failed", errors)

    def close_stderr_log(self) -> None:
        with self.stderr_log_lock:
            if self.stderr_log_fh is not None:
                self.stderr_log_fh.close()
                self.stderr_log_fh = None


# ---------------------------------------------------------------------------
# Stdio subprocess stderr redirection
# ---------------------------------------------------------------------------
#
# The MCP SDK's ``stdio_client(server, errlog=sys.stderr)`` defaults the
# subprocess stderr stream to the parent process's real stderr, i.e. the
# user's TTY.  That means any MCP server we spawn at startup (FastMCP
# banners, slack-mcp-server JSON startup logs, etc.) writes directly onto
# the terminal while prompt_toolkit / Rich is rendering the TUI — which
# corrupts the display and can hang the session.
#
# Instead we redirect every stdio MCP subprocess's stderr into a shared
# per-profile log file (agentspace/logs/mcp-stderr.log), tagged with the
# server name so individual servers remain debuggable.
#
# Fallback is os.devnull if opening the log file fails for any reason.


def _get_mcp_stderr_log(core: MCPCore) -> IO[str]:
    """Return a shared append-mode file handle for MCP subprocess stderr.

    Opened once per process and reused for every stdio server.  Must have a
    real OS-level file descriptor (``fileno()``) because asyncio's subprocess
    machinery wires the child's stderr directly to that fd.  Falls back to
    ``/dev/null`` if opening the log file fails.
    """
    with core.stderr_log_lock:
        if core.stderr_log_fh is not None:
            return core.stderr_log_fh
        log_dir = core.context.agentspace / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        core.stderr_log_fh = open(
            log_dir / "mcp-stderr.log", "a", encoding="utf-8",
            errors="replace", buffering=1,
        )
        return core.stderr_log_fh


def _write_stderr_log_header(core: MCPCore, server_name: str) -> None:
    """Write a human-readable session marker before launching a server.

    Gives operators a way to find each server's output in the shared
    ``mcp-stderr.log`` file without needing per-line prefixes (which would
    require a pipe + reader thread and complicate shutdown).
    """
    fh = _get_mcp_stderr_log(core)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fh.write(f"\n===== [{ts}] starting MCP server '{server_name}' =====\n")
    fh.flush()

# ---------------------------------------------------------------------------
# Graceful import -- MCP SDK is an optional dependency
# ---------------------------------------------------------------------------

_MCP_AVAILABLE = False
_MCP_HTTP_AVAILABLE = False
_MCP_SAMPLING_TYPES = False
ErrorData = None  # type checker fallback — always bound
_MCP_NOTIFICATION_TYPES = False
_MCP_MESSAGE_HANDLER_SUPPORTED = False
# Conservative fallback for SDK builds that don't export LATEST_PROTOCOL_VERSION.
# Streamable HTTP was introduced by 2025-03-26, so this remains valid for the
# HTTP transport path even on older-but-supported SDK versions.
LATEST_PROTOCOL_VERSION = "2025-03-26"
try:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters
    from mcp.types import TextContent, ImageContent, TextResourceContents, BlobResourceContents
    _MCP_AVAILABLE = True
    try:
        from mcp.client.streamable_http import streamablehttp_client
        _MCP_HTTP_AVAILABLE = True
    except ImportError:
        _MCP_HTTP_AVAILABLE = False
    # Prefer the non-deprecated API (mcp >= 1.24.0); fall back to the
    # deprecated wrapper for older SDK versions.
    try:
        from mcp.client.streamable_http import streamable_http_client
        _MCP_NEW_HTTP = True
    except ImportError:
        _MCP_NEW_HTTP = False
    try:
        from mcp.types import LATEST_PROTOCOL_VERSION
    except ImportError:
        logger.debug("mcp.types.LATEST_PROTOCOL_VERSION not available -- using fallback protocol version")
    # SSE transport client (for MCP servers using SSE transport instead of Streamable HTTP)
    try:
        from mcp.client.sse import sse_client
    except ImportError:
        sse_client = None
        logger.debug("mcp.client.sse.sse_client not available -- SSE transport disabled")
    # Sampling types -- separated so older SDK versions don't break MCP support
    try:
        from mcp.types import (
            CreateMessageResult,
            CreateMessageResultWithTools,
            ErrorData,
            SamplingCapability,
            SamplingToolsCapability,
            TextContent,
            ToolUseContent,
            ToolResultContent,
        )
        _MCP_SAMPLING_TYPES = True
    except ImportError:
        logger.debug("MCP sampling types not available -- sampling disabled")
    # Notification types for dynamic tool discovery (tools/list_changed)
    try:
        from mcp.types import (
            ServerNotification,
            ToolListChangedNotification,
            PromptListChangedNotification,
            ResourceListChangedNotification,
        )
        _MCP_NOTIFICATION_TYPES = True
    except ImportError:
        logger.debug("MCP notification types not available -- dynamic tool discovery disabled")
except ImportError:
    _MCP_AVAILABLE = False
    logger.debug("mcp package not installed -- MCP tool support disabled")
    ClientSession = None  # type: ignore[assignment,misc]
    StdioServerParameters = None  # type: ignore[assignment,misc]
    streamablehttp_client = None  # type: ignore[assignment,misc]
    streamable_http_client = None  # type: ignore[assignment,misc]
    sse_client = None  # type: ignore[assignment,misc]
    CreateMessageResult = None  # type: ignore[assignment,misc]
    CreateMessageResultWithTools = None  # type: ignore[assignment,misc]
    SamplingCapability = None  # type: ignore[assignment,misc]
    SamplingToolsCapability = None  # type: ignore[assignment,misc]
    TextContent = None  # type: ignore[assignment,misc]
    ToolUseContent = None  # type: ignore[assignment,misc]
    ServerNotification = None  # type: ignore[assignment,misc]
    ToolListChangedNotification = None  # type: ignore[assignment,misc]
    PromptListChangedNotification = None  # type: ignore[assignment,misc]
    ResourceListChangedNotification = None  # type: ignore[assignment,misc]
    _MCP_NEW_HTTP = False


def _check_message_handler_support() -> bool:
    """Check if ClientSession accepts ``message_handler`` kwarg.

    Inspects the constructor signature for backward compatibility with older
    MCP SDK versions that don't support notification handlers.
    """
    if not _MCP_AVAILABLE:
        return False
    try:
        return "message_handler" in inspect.signature(ClientSession).parameters
    except (TypeError, ValueError):
        return False


_MCP_MESSAGE_HANDLER_SUPPORTED = _check_message_handler_support()
if _MCP_AVAILABLE and not _MCP_MESSAGE_HANDLER_SUPPORTED:
    logger.debug("MCP SDK does not support message_handler -- dynamic tool discovery disabled")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Environment variables that are safe to pass to stdio subprocesses
_SAFE_ENV_KEYS = frozenset({
    "PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "SHELL", "TMPDIR",
})

# Regex for credential patterns to strip from error messages
_CREDENTIAL_PATTERN = re.compile(
    r"(?:"
    r"ghp_[A-Za-z0-9_]{1,255}"           # GitHub PAT
    r"|sk-[A-Za-z0-9_]{1,255}"           # OpenAI-style key
    r"|Bearer\s+\S+"                      # Bearer token
    r"|token=[^\s&,;\"']{1,255}"         # token=...
    r"|key=[^\s&,;\"']{1,255}"           # key=...
    r"|API_KEY=[^\s&,;\"']{1,255}"       # API_KEY=...
    r"|password=[^\s&,;\"']{1,255}"      # password=...
    r"|secret=[^\s&,;\"']{1,255}"        # secret=...
    r")",
    re.IGNORECASE,
)

# Pre-compiled pattern for ${VAR_NAME} style env-var interpolation.
# Supports any non-} characters in the variable name (hyphens, dots, etc.)
# so providers like MY-VAR or my.var work correctly.
_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------

def _build_safe_env(user_env: dict | None) -> dict:
    """Build a filtered environment dict for stdio subprocesses.

    Only passes through safe baseline variables (PATH, HOME, etc.) and XDG_*
    variables from the current process environment, plus any variables
    explicitly specified by the user in the server config.

    This prevents accidentally leaking secrets like API keys, tokens, or
    credentials to MCP server subprocesses.
    """
    env = {}
    for key, value in os.environ.items():
        if key in _SAFE_ENV_KEYS or key.startswith("XDG_"):
            env[key] = value
    if user_env:
        env.update(user_env)
    return env


def _sanitize_error(text: str) -> str:
    """Strip credential-like patterns from error text before returning to LLM.

    Replaces tokens, keys, and other secrets with [REDACTED] to prevent
    accidental credential exposure in tool error responses.
    """
    return _CREDENTIAL_PATTERN.sub("[REDACTED]", text)


def _exc_str(exc: BaseException) -> str:
    """Return a non-empty human-readable string for *exc*.

    Some exception classes (e.g. ``anyio.ClosedResourceError``) are raised
    without a message argument, so ``str(exc)`` is ``""``.  This helper
    falls back to ``repr(exc)`` so that error messages shown to the user
    and logged to disk always carry *some* diagnostic information.
    """
    text = str(exc).strip()
    return text if text else repr(exc)


# ---------------------------------------------------------------------------
# MCP tool description content scanning
# ---------------------------------------------------------------------------

# Patterns that indicate potential prompt injection in MCP tool descriptions.
# These are WARNING-level — we log but don't block, since false positives
# would break legitimate MCP servers.
_MCP_INJECTION_PATTERNS = [
    (re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.I),
     "prompt override attempt ('ignore previous instructions')"),
    (re.compile(r"you\s+are\s+now\s+a", re.I),
     "identity override attempt ('you are now a...')"),
    (re.compile(r"your\s+new\s+(task|role|instructions?)\s+(is|are)", re.I),
     "task override attempt"),
    (re.compile(r"system\s*:\s*", re.I),
     "system prompt injection attempt"),
    (re.compile(r"<\s*(system|human|assistant)\s*>", re.I),
     "role tag injection attempt"),
    (re.compile(r"do\s+not\s+(tell|inform|mention|reveal)", re.I),
     "concealment instruction"),
    (re.compile(r"(curl|wget|fetch)\s+https?://", re.I),
     "network command in description"),
    (re.compile(r"base64\.(b64decode|decodebytes)", re.I),
     "base64 decode reference"),
    (re.compile(r"exec\s*\(|eval\s*\(", re.I),
     "code execution reference"),
    (re.compile(r"import\s+(subprocess|os|shutil|socket)", re.I),
     "dangerous import reference"),
]


def _scan_mcp_description(server_name: str, tool_name: str, description: str) -> list[str]:
    """Scan an MCP tool description for prompt injection patterns.

    Returns a list of finding strings (empty = clean).
    """
    findings = []
    if not description:
        return findings
    for pattern, reason in _MCP_INJECTION_PATTERNS:
        if pattern.search(description):
            findings.append(reason)
    if findings:
        logger.warning(
            "MCP server '%s' tool '%s': suspicious description content — %s. "
            "Description: %.200s",
            server_name, tool_name, "; ".join(findings),
            description,
        )
    return findings


def _prepend_path(env: dict, directory: str) -> dict:
    """Prepend *directory* to env PATH if it is not already present."""
    updated = dict(env or {})
    if not directory:
        return updated

    existing = updated.get("PATH", "")
    parts = [part for part in existing.split(os.pathsep) if part]
    if directory not in parts:
        parts = [directory, *parts]
    updated["PATH"] = os.pathsep.join(parts) if parts else directory
    return updated


def _resolve_stdio_command(command: str, env: dict) -> tuple[str, dict]:
    """Resolve a stdio MCP command against the exact subprocess environment.

    This primarily exists to make bare ``npx``/``npm``/``node`` commands work
    reliably even when MCP subprocesses run under a filtered PATH.
    """
    resolved_command = os.path.expanduser(str(command).strip())
    resolved_env = dict(env or {})

    if os.sep not in resolved_command:
        path_arg = resolved_env["PATH"] if "PATH" in resolved_env else None
        which_hit = shutil.which(resolved_command, path=path_arg)
        if which_hit:
            resolved_command = which_hit
        elif resolved_command in {"npx", "npm", "node"}:
            candidates = [
                os.path.join(os.path.expanduser("~"), ".local", "bin", resolved_command),
            ]
            for candidate in candidates:
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    resolved_command = candidate
                    break

    command_dir = os.path.dirname(resolved_command)
    if command_dir:
        resolved_env = _prepend_path(resolved_env, command_dir)

    return resolved_command, resolved_env


# ---------------------------------------------------------------------------
# Remote MCP URL validation
# ---------------------------------------------------------------------------


class InvalidMcpUrlError(ValueError):
    """Raised when a remote MCP server's ``url`` cannot be parsed as http(s)://.

    Validated once at startup so we fail fast with a clear message instead of
    burning through the reconnect-backoff loop on every attempt.  (Ported from
    anomalyco/opencode#25019.)
    """


def _validate_remote_mcp_url(server_name: str, url: object) -> str:
    """Return the URL as a string if it's a valid http(s) remote MCP URL.

    Raises :class:`InvalidMcpUrlError` otherwise with a message naming the
    offending server, so users can spot the bad entry in their config.

    Accepts:
    - ``http://host`` / ``https://host`` with optional port, path, query
    - IPv4, IPv6 (bracketed), DNS hostnames

    Rejects:
    - Non-string values (``None``, dicts, ints)
    - Missing scheme (``example.com/mcp``)
    - Non-http(s) schemes (``file://``, ``ws://``, ``stdio:`` — stdio servers
      use the ``command`` key, not ``url``)
    - Empty host (``http://``, ``https:///path``)
    """
    if not isinstance(url, str):
        raise InvalidMcpUrlError(
            f"Invalid MCP URL for '{server_name}': expected a string, got "
            f"{type(url).__name__}"
        )
    stripped = url.strip()
    if not stripped:
        raise InvalidMcpUrlError(
            f"Invalid MCP URL for '{server_name}': empty url"
        )
    try:
        parsed = urlparse(stripped)
    except Exception as exc:  # urlparse is very permissive — belt and braces
        raise InvalidMcpUrlError(
            f"Invalid MCP URL for '{server_name}': {stripped!r} ({exc})"
        ) from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise InvalidMcpUrlError(
            f"Invalid MCP URL for '{server_name}': scheme must be http or "
            f"https, got {parsed.scheme!r} ({stripped!r})"
        )
    if not parsed.netloc:
        raise InvalidMcpUrlError(
            f"Invalid MCP URL for '{server_name}': missing host ({stripped!r})"
        )
    # ``urlparse`` accepts ``http://:8080`` (empty host, explicit port).
    # Reject that — we need a real host.
    if not parsed.hostname:
        raise InvalidMcpUrlError(
            f"Invalid MCP URL for '{server_name}': missing hostname "
            f"({stripped!r})"
        )
    return stripped


# ---------------------------------------------------------------------------
# Sampling -- server-initiated LLM requests (MCP sampling/createMessage)
# ---------------------------------------------------------------------------

class SamplingHandler:
    """Handles sampling/createMessage requests for a single MCP server.

    Each MCPServerTask that has sampling enabled creates one SamplingHandler.
    The handler is callable and passed directly to ``ClientSession`` as
    the ``sampling_callback``.  All state (rate-limit timestamps, metrics,
    tool-loop counters) lives on the instance -- no module-level globals.

    The callback is async and runs on the MCP background event loop.  The
    sync LLM call is offloaded to a thread via ``asyncio.to_thread()`` so
    it doesn't block the event loop.
    """

    _STOP_REASON_MAP = {"stop": "endTurn", "length": "maxTokens", "tool_calls": "toolUse"}

    def __init__(self, server: MCPServerTask, config: dict, call_llm: Callable | None = None):
        self._server = server
        self.server_name = server.name
        self._call_llm = call_llm
        self.max_rpm = config.get("max_rpm", 10)
        self.timeout = config.get("timeout", 30)
        self.max_tokens_cap = config.get("max_tokens_cap", 4096)
        self.max_tool_rounds = config.get("max_tool_rounds", 5)
        self.model_override = config.get("model")
        self.allowed_models = config.get("allowed_models", [])

        _log_levels = {"debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING}
        self.audit_level = _log_levels.get(
            str(config.get("log_level", "info")).lower(), logging.INFO,
        )

        # Per-instance state
        self._rate_timestamps: list[float] = []
        self._tool_loop_count = 0
        self.metrics = {"requests": 0, "errors": 0, "tokens_used": 0, "tool_use_count": 0}

    # -- Rate limiting -------------------------------------------------------

    def _check_rate_limit(self) -> bool:
        """Sliding-window rate limiter.  Returns True if request is allowed."""
        now = time.time()
        window = now - 60
        self._rate_timestamps[:] = [t for t in self._rate_timestamps if t > window]
        if len(self._rate_timestamps) >= self.max_rpm:
            return False
        self._rate_timestamps.append(now)
        return True

    # -- Model resolution ----------------------------------------------------

    def _resolve_model(self, preferences) -> str | None:
        """Config override > server hint > None (use default)."""
        if self.model_override:
            return self.model_override
        if preferences is not None and preferences.hints:
            for hint in preferences.hints:
                if hint.name:
                    return hint.name
        return None

    # -- Message conversion --------------------------------------------------

    @staticmethod
    def _extract_tool_result_text(block: ToolResultContent) -> str:
        return "\n".join(item.text for item in block.content if isinstance(item, TextContent))

    def _convert_messages(self, params) -> list[dict]:
        """Convert MCP SamplingMessages to OpenAI format.

        Uses ``msg.content_as_list`` (SDK helper) so single-block and
        list-of-blocks are handled uniformly. SDK content types are explicit;
        fixed model fields are never guessed through reflection.
        """
        messages: list[dict] = []
        for msg in params.messages:
            blocks = msg.content_as_list
            tool_results = [b for b in blocks if isinstance(b, ToolResultContent)]
            tool_uses = [b for b in blocks if isinstance(b, ToolUseContent)]
            content_blocks = [b for b in blocks if not isinstance(b, (ToolResultContent, ToolUseContent))]

            # Emit tool result messages (role: tool)
            for tr in tool_results:
                messages.append({
                    "role": Role.TOOL,
                    "tool_call_id": tr.toolUseId,
                    "content": self._extract_tool_result_text(tr),
                })

            # Emit assistant tool_calls message
            if tool_uses:
                tc_list = []
                for tu in tool_uses:
                    tc_list.append({
                        "id": tu.id,
                        "type": "function",
                        "function": {
                            "name": tu.name,
                            "arguments": json.dumps(tu.input, ensure_ascii=False) if isinstance(tu.input, dict) else str(tu.input),
                        },
                    })
                msg_dict: dict = {"role": msg.role, "tool_calls": tc_list}
                # Include any accompanying text
                text_parts = [b.text for b in content_blocks if isinstance(b, TextContent)]
                if text_parts:
                    msg_dict["content"] = "\n".join(text_parts)
                messages.append(msg_dict)
            elif content_blocks:
                # Pure text/image content
                if len(content_blocks) == 1 and isinstance(content_blocks[0], TextContent):
                    messages.append({"role": msg.role, "content": content_blocks[0].text})
                else:
                    parts = []
                    for block in content_blocks:
                        if isinstance(block, TextContent):
                            parts.append({"type": "text", "text": block.text})
                        elif isinstance(block, ImageContent):
                            parts.append({
                                "type": "image_url",
                                "image_url": {"url": f"data:{block.mimeType};base64,{block.data}"},
                            })
                        else:
                            logger.warning(
                                "Unsupported sampling content block type: %s (skipped)",
                                type(block).__name__,
                            )
                    if parts:
                        messages.append({"role": msg.role, "content": parts})

        return messages

    # -- Error helper --------------------------------------------------------

    @staticmethod
    def _error(message: str, code: int = -1):
        """Return ErrorData (MCP spec) or raise as fallback."""
        if ErrorData is not None:
            return ErrorData(code=code, message=message)
        raise Exception(message)

    # -- Response building ---------------------------------------------------

    def _build_tool_use_result(self, choice, response):
        """Build a CreateMessageResultWithTools from an LLM tool_calls response."""
        self.metrics["tool_use_count"] += 1

        # Tool loop governance
        if self.max_tool_rounds == 0:
            self._tool_loop_count = 0
            return self._error(
                f"Tool loops disabled for server '{self.server_name}' (max_tool_rounds=0)"
            )

        self._tool_loop_count += 1
        if self._tool_loop_count > self.max_tool_rounds:
            self._tool_loop_count = 0
            return self._error(
                f"Tool loop limit exceeded for server '{self.server_name}' "
                f"(max {self.max_tool_rounds} rounds)"
            )

        content_blocks = []
        for tc in choice.message.tool_calls:
            args = tc.function.arguments
            if isinstance(args, str):
                try:
                    parsed = json.loads(args)
                except (json.JSONDecodeError, ValueError):
                    logger.warning(
                        "MCP server '%s': malformed tool_calls arguments "
                        "from LLM (wrapping as raw): %.100s",
                        self.server_name, args,
                    )
                    parsed = {"_raw": args}
            else:
                parsed = args if isinstance(args, dict) else {"_raw": str(args)}

            content_blocks.append(ToolUseContent(
                type="tool_use",
                id=tc.id,
                name=tc.function.name,
                input=parsed,
            ))

        logger.log(
            self.audit_level,
            "MCP server '%s' sampling response: model=%s, tokens=%s, tool_calls=%d",
            self.server_name, response.model,
            response.usage.total_tokens,
            len(content_blocks),
        )

        return CreateMessageResultWithTools(
            role="assistant",
            content=content_blocks,
            model=response.model,
            stopReason="toolUse",
        )

    def _build_text_result(self, choice, response):
        """Build a CreateMessageResult from a normal text response."""
        self._tool_loop_count = 0  # reset on text response
        response_text = choice.message.content or ""

        logger.log(
            self.audit_level,
            "MCP server '%s' sampling response: model=%s, tokens=%s",
            self.server_name, response.model,
            response.usage.total_tokens,
        )

        return CreateMessageResult(
            role="assistant",
            content=TextContent(type="text", text=_sanitize_error(response_text)),
            model=response.model,
            stopReason=self._STOP_REASON_MAP.get(choice.finish_reason, "endTurn"),
        )

    # -- Session kwargs helper -----------------------------------------------

    def session_kwargs(self) -> dict:
        """Return kwargs to pass to ClientSession for sampling support."""
        return {
            "sampling_callback": self,
            "sampling_capabilities": SamplingCapability(
                tools=SamplingToolsCapability(),
            ),
        }

    # -- Main callback -------------------------------------------------------

    async def __call__(self, context, params):
        try:
            return await self._server.request(lambda: self._sample(context, params))
        except ApplicationStoppingError:
            return self._error("MCP sampling is closed")

    async def _sample(self, context, params):
        """Sampling callback invoked by the MCP SDK.

        Conforms to ``SamplingFnT`` protocol.  Returns
        ``CreateMessageResult``, ``CreateMessageResultWithTools``, or
        ``ErrorData``.
        """
        # Rate limit
        if not self._check_rate_limit():
            logger.warning(
                "MCP server '%s' sampling rate limit exceeded (%d/min)",
                self.server_name, self.max_rpm,
            )
            self.metrics["errors"] += 1
            return self._error(
                f"Sampling rate limit exceeded for server '{self.server_name}' "
                f"({self.max_rpm} requests/minute)"
            )

        # Resolve model
        model = self._resolve_model(params.modelPreferences)

        # Get auxiliary LLM client. If no call_llm callback was provided,
        # return an error — the host application must supply this.
        if self._call_llm is None:
            logger.warning(
                "MCP server '%s' sampling requested but no call_llm callback configured",
                self.server_name,
            )
            self.metrics["errors"] += 1
            return self._error(
                f"Sampling requested for server '{self.server_name}' but no "
                f"LLM callback is configured"
            )

        # Model whitelist check (we need to resolve model before calling)
        resolved_model = model or self.model_override or ""

        if self.allowed_models and resolved_model and resolved_model not in self.allowed_models:
            logger.warning(
                "MCP server '%s' requested model '%s' not in allowed_models",
                self.server_name, resolved_model,
            )
            self.metrics["errors"] += 1
            return self._error(
                f"Model '{resolved_model}' not allowed for server "
                f"'{self.server_name}'. Allowed: {', '.join(self.allowed_models)}"
            )

        # Convert messages
        messages = self._convert_messages(params)
        if params.systemPrompt:
            messages.insert(0, {"role": Role.SYSTEM, "content": params.systemPrompt})

        # Build LLM call kwargs
        max_tokens = min(params.maxTokens, self.max_tokens_cap)
        call_temperature = None
        if params.temperature is not None:
            call_temperature = params.temperature

        # Forward server-provided tools
        call_tools = None
        server_tools = params.tools
        if server_tools:
            call_tools = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description or "",
                        "parameters": _normalize_mcp_input_schema(
                            t.inputSchema
                        ),
                    },
                }
                for t in server_tools
            ]

        logger.log(
            self.audit_level,
            "MCP server '%s' sampling request: model=%s, max_tokens=%d, messages=%d",
            self.server_name, resolved_model, max_tokens, len(messages),
        )

        # Offload sync LLM call to thread (non-blocking)
        # Use self._call_llm (set during init) or fall back to error
        call_llm = self._call_llm

        def _sync_call():
            with self._server._admit_request():
                pass
            return call_llm(
                task="mcp",
                model=resolved_model or None,
                messages=messages,
                temperature=call_temperature,
                max_tokens=max_tokens,
                tools=call_tools,
                timeout=self.timeout,
            )

        try:
            response = await asyncio.wait_for(
                self._server.core.native.run(_sync_call), timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            self.metrics["errors"] += 1
            return self._error(
                f"Sampling LLM call timed out after {self.timeout}s "
                f"for server '{self.server_name}'"
            )
        except Exception as exc:
            if requires_lifecycle_propagation(exc):
                raise
            self.metrics["errors"] += 1
            return self._error(
                f"Sampling LLM call failed: {_sanitize_error(_exc_str(exc))}"
            )

        # Guard against empty choices (content filtering, provider errors)
        if not response.choices:
            self.metrics["errors"] += 1
            return self._error(
                f"LLM returned empty response (no choices) for server "
                f"'{self.server_name}'"
            )

        # Track metrics
        choice = response.choices[0]
        self.metrics["requests"] += 1
        total_tokens = response.usage.total_tokens
        if isinstance(total_tokens, int):
            self.metrics["tokens_used"] += total_tokens

        # Dispatch based on response type
        if (
            choice.finish_reason == "tool_calls"
            and choice.message.tool_calls
        ):
            return self._build_tool_use_result(choice, response)

        return self._build_text_result(choice, response)


# ---------------------------------------------------------------------------
# Server task -- each MCP server lives in one long-lived asyncio Task
# ---------------------------------------------------------------------------

class MCPServerTask:
    """Manages a single MCP server connection in a dedicated asyncio Task.

    The entire connection lifecycle (connect, discover, serve, disconnect)
    runs inside one asyncio Task so that anyio cancel-scopes created by
    the transport client are entered and exited in the same Task context.

    Supports both stdio and HTTP/StreamableHTTP transports.
    """

    __slots__ = (
        "name", "core", "session", "tool_timeout",
        "_task", "_ready", "_shutdown_event", "_reconnect_event",
        "_tools", "_error", "_config",
        "_sampling", "_registered_tool_names", "_auth_type", "_refresh_lock",
        "_rpc_lock", "_background", "_requests", "_connection_owner",
        "_close_task", "_stop_task", "_transports", "_serving", "_registered",
        "initialize_result",
    )

    def __init__(self, name: str, core: MCPCore):
        self.name = name
        self.core = core
        self.session: ClientSession | None = None
        self.tool_timeout: float = _DEFAULT_TOOL_TIMEOUT
        self._task: asyncio.Task | None = None
        self._ready = asyncio.Event()
        self._shutdown_event = asyncio.Event()
        # Set by tool handlers on auth failure after manager.handle_401()
        # confirms recovery is viable. When set, _run_http / _run_stdio
        # exit their async-with blocks cleanly (no exception), and the
        # outer run() loop re-enters the transport so the MCP session is
        # rebuilt with fresh credentials.
        self._reconnect_event = asyncio.Event()
        self._tools: list = []
        self._error: BaseException | None = None
        self._config: dict = {}
        self._sampling: SamplingHandler | None = None
        self._registered_tool_names: list[str] = []
        self._auth_type: str = ""
        self._refresh_lock = asyncio.Lock()
        # MCP stdio sessions are a single JSON-RPC stream. Some servers emit
        # list_changed notifications during startup; if the notification
        # handler calls list_tools while a normal tool call is in flight, the
        # stream can wedge and the user-visible tool call times out. Serialize
        # client-initiated RPCs per server. The lock is also applied to HTTP
        # transports for conservative per-server ordering.
        self._rpc_lock = asyncio.Lock()
        self._background = TaskOwner(f"mcp-notifications-{name}", core.runtime.record_failure)
        self._requests = TaskOwner(f"mcp-requests-{name}", core.runtime.record_failure)
        self._connection_owner = TaskOwner(f"mcp-connection-{name}", core.runtime.record_failure)
        self._close_task: asyncio.Task[None] | None = None
        self._stop_task: asyncio.Task[None] | None = None
        self._transports: list[MCPStdioTransport] = []
        self._serving = False
        self._registered = asyncio.Event()
        # Captures the ``InitializeResult`` returned by
        # ``await session.initialize()`` so downstream code can inspect the
        # server's real advertised capabilities (``.capabilities.resources``,
        # ``.capabilities.prompts``) instead of assuming every ``ClientSession``
        # method attribute corresponds to a supported server method. See #18051.
        self.initialize_result: InitializeResult | None = None

    def _is_http(self) -> bool:
        """Check if this server uses HTTP transport."""
        return "url" in self._config

    # ----- Dynamic tool discovery (notifications/tools/list_changed) -----

    async def _refresh_tools_task(self) -> None:
        # 初始化期通知先等待初次发现完成，不能提前注册半初始化工具。
        await self._registered.wait()
        await self._ready.wait()
        if self._error is not None or self._shutdown_event.is_set() or self.core.closed:
            return
        try:
            await self._refresh_tools()
        except ApplicationStoppingError:
            return

    def _schedule_tools_refresh(self) -> None:
        if self._shutdown_event.is_set() or self.core.closed:
            return
        self._background.create(self._refresh_tools_task(), name=f"mcp-refresh-tools-{self.name}")

    def _make_message_handler(self):
        async def handler(message) -> None:
            if isinstance(message, Exception):
                # 协议解析失败属于该连接的后台故障，不仅打印后消失。
                self.core.runtime.record_failure(message)
                return
            if _MCP_NOTIFICATION_TYPES and isinstance(message, ServerNotification):
                if isinstance(message.root, ToolListChangedNotification):
                    self._schedule_tools_refresh()
        return handler

    @contextmanager
    def _admit_request(self) -> Iterator[None]:
        with self.core.admission():
            if self._shutdown_event.is_set():
                raise ApplicationStoppingError(f"MCP server '{self.name}' is stopping")
            yield

    def require_session(self) -> ClientSession:
        with self._admit_request():
            if self.session is None:
                raise ConnectionError(f"MCP server '{self.name}' is disconnected")
            return self.session

    async def request(self, factory: Callable[[], Coroutine[Any, Any, Any]]) -> Any:
        return await self._requests.run_request(
            factory, name=f"mcp-rpc-{self.name}", admission=self._admit_request,
        )

    async def reconnect(self) -> bool:
        async with self._refresh_lock:
            with self._admit_request():
                if self._task is None or self._task.done():
                    return False
                self._ready.clear()
                self.session = None
                self._reconnect_event.set()
            await self._ready.wait()
            if self._error is not None:
                raise self._error
            return self.session is not None and not self._shutdown_event.is_set()

    async def _refresh_tools(self):
        """Re-fetch tools from the server and update the registry.

        Called when the server sends ``notifications/tools/list_changed``.
        The lock prevents overlapping refreshes from rapid-fire notifications.
        After the initial ``await`` (list_tools), all mutations are synchronous
        — atomic from the event loop's perspective.
        """
        registry = self.core.registry

        async with self._refresh_lock:
            # Capture old tool names for change diff
            old_tool_names = set(self._registered_tool_names)

            # 1. Fetch current tool list from server
            async with self._rpc_lock:
                with self.core.setup_admission():
                    if self._shutdown_event.is_set():
                        raise ApplicationStoppingError("MCP server is stopping")
                session = self.session
                if session is None:
                    return  # 重连期间旧传输的通知失效，新的initialize负责发现。
                tools_result = await session.list_tools()
            with self.core.setup_admission():
                pass
            new_mcp_tools = tools_result.tools

            # 2. Re-register with fresh tool list. Avoid nuke-and-repave for
            # all names: live agent turns may already have tool-call IDs
            # pointing at existing handler functions. Replacing entries
            # in-place is enough for unchanged names and avoids transient
            # "tool not connected" / stale-handler races during startup
            # notifications. Tools absent from the fresh list are no longer
            # callable, so remove only those stale registry entries first.
            stale_tool_names = old_tool_names - {
                f"mcp_{sanitize_mcp_name_component(self.name)}_"
                f"{sanitize_mcp_name_component(tool.name)}"
                for tool in new_mcp_tools
            }
            for tool_name in stale_tool_names:
                registry.deregister(tool_name)

            # 3. Re-register with fresh tool list
            self._tools = new_mcp_tools
            self._registered_tool_names = _register_server_tools(
                self.name, self, self._config
            )

            # 5. Log what changed (user-visible notification)
            new_tool_names = set(self._registered_tool_names)
            added = new_tool_names - old_tool_names
            removed = old_tool_names - new_tool_names
            changes = []
            if added:
                changes.append(f"added: {', '.join(sorted(added))}")
            if removed:
                changes.append(f"removed: {', '.join(sorted(removed))}")
            if changes:
                logger.warning(
                    "MCP server '%s': tools changed dynamically — %s. "
                    "Verify these changes are expected.",
                    self.name, "; ".join(changes),
                )
            else:
                logger.info(
                    "MCP server '%s': dynamically refreshed %d tool(s) (no changes)",
                    self.name, len(self._registered_tool_names),
                )

    async def _wait_for_lifecycle_event(self) -> str:
        """Keep one transport alive; both waiters are structurally owned."""
        async with asyncio.TaskGroup() as group:
            shutdown = group.create_task(self._shutdown_event.wait())
            reconnect = group.create_task(self._reconnect_event.wait())
            try:
                while True:
                    done, _ = await asyncio.wait(
                        {shutdown, reconnect}, timeout=180,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if done:
                        break
                    if self.core.closed:
                        # 停止业务后只等待最终连接关闭，不再发起keepalive/RPC。
                        await shutdown
                        break
                    async with self._rpc_lock:
                        with self.core.setup_admission():
                            pass
                        async with asyncio.timeout(30):
                            await self.session.list_tools()
            except ApplicationStoppingError:
                await shutdown
            finally:
                shutdown.cancel()
                reconnect.cancel()
        if self._shutdown_event.is_set():
            return "shutdown"
        self._reconnect_event.clear()
        return "reconnect"

    async def _run_stdio(self, config: dict):
        """Run the server using stdio transport."""
        command = config.get("command")
        args = config.get("args", [])
        user_env = config.get("env")

        if not command:
            raise ValueError(
                f"MCP server '{self.name}' has no 'command' in config"
            )

        safe_env = _build_safe_env(user_env)
        command, safe_env = _resolve_stdio_command(command, safe_env)

        # OSV malware check is not available in the
        # standalone MCP client. Skip it.

        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=safe_env if safe_env else None,
        )

        sampling_kwargs = self._sampling.session_kwargs() if self._sampling else {}
        if _MCP_NOTIFICATION_TYPES and _MCP_MESSAGE_HANDLER_SUPPORTED:
            sampling_kwargs["message_handler"] = self._make_message_handler()

        from .stdio import MCPStdioTransport

        _write_stderr_log_header(self.core, self.name)
        transport = MCPStdioTransport(
            server_params, _get_mcp_stderr_log(self.core), self.core.runtime.record_failure,
        )
        self._transports.append(transport)
        async with transport.open() as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream, **sampling_kwargs) as session:
                self.initialize_result = await session.initialize()
                self.session = session
                await self._discover_tools()
                self._ready.set()
                await self._wait_for_lifecycle_event()
        if transport.is_idle:
            self._transports.remove(transport)

    async def _run_http(self, config: dict):
        """Run the server using HTTP/StreamableHTTP transport."""
        if not _MCP_HTTP_AVAILABLE:
            raise ImportError(
                f"MCP server '{self.name}' requires HTTP transport but "
                "mcp.client.streamable_http is not available. "
                "Upgrade the mcp package to get HTTP support."
            )

        url = config["url"]
        headers = dict(config.get("headers") or {})
        # Some MCP servers require MCP-Protocol-Version on the initial
        # initialize request and reject session-less POSTs otherwise.
        # Seed it as a client-level default, but treat user overrides as
        # case-insensitive so conventional casing is preserved.
        if not any(key.lower() == "mcp-protocol-version" for key in headers):
            headers["mcp-protocol-version"] = LATEST_PROTOCOL_VERSION
        connect_timeout = config.get("connect_timeout", _DEFAULT_CONNECT_TIMEOUT)
        ssl_verify = config.get("ssl_verify", True)

        # OAuth 2.1 PKCE: route through the central MCPOAuthManager so the
        # same provider instance is reused across reconnects, pre-flow
        # disk-watch is active, and config-time CLI code paths share state.
        # If OAuth setup fails (e.g. non-interactive env without cached
        # tokens), re-raise so this server is reported as failed without
        # blocking other MCP servers from connecting.
        _oauth_auth = None
        if self._auth_type == "oauth":
            try:
                _oauth_auth = self.core.oauth_manager.get_or_build_provider(
                    self.name, url, config.get("oauth"),
                )
            except Exception as exc:
                logger.warning("MCP OAuth setup failed for '%s': %s", self.name, exc)
                raise

        sampling_kwargs = self._sampling.session_kwargs() if self._sampling else {}
        if _MCP_NOTIFICATION_TYPES and _MCP_MESSAGE_HANDLER_SUPPORTED:
            sampling_kwargs["message_handler"] = self._make_message_handler()

        # SSE transport (for MCP servers that implement the SSE transport protocol
        # rather than Streamable HTTP). Configure with ``transport: sse`` in the
        # mcp_servers entry in config.yaml.
        if config.get("transport") == "sse":
            if sse_client is None:
                raise ImportError(
                    f"MCP server '{self.name}' requires SSE transport but "
                    "mcp.client.sse.sse_client is not available. "
                    "Upgrade the mcp package to get SSE support."
                )
            # sse_read_timeout governs how long sse_client will wait between
            # events on the SSE stream. Using the tool_timeout (default 60s)
            # here is wrong: SSE servers commonly hold the stream idle for
            # minutes between events, so a 60s read timeout drops the
            # connection after the first slow stretch. 300s matches the
            # Streamable HTTP code path's httpx read timeout below. Original
            # observation from @amiller in PR #5981 (Router Teamwork,
            # Supermemory on Cloudflare Workers idle-disconnect at ~60s).
            _sse_kwargs: dict = {
                "url": url,
                "headers": headers or None,
                "timeout": float(connect_timeout),
                "sse_read_timeout": _SSE_READ_TIMEOUT,
            }
            if _oauth_auth is not None:
                # Pass OAuth auth through to sse_client so SSE MCP servers
                # behind OAuth 2.1 PKCE work. Previously built but never
                # forwarded — SSE OAuth would silently fail with 401s.
                _sse_kwargs["auth"] = _oauth_auth
            async with sse_client(**_sse_kwargs) as (read_stream, write_stream):
                async with ClientSession(
                    read_stream, write_stream, **sampling_kwargs
                ) as session:
                    self.initialize_result = await session.initialize()
                    self.session = session
                    await self._discover_tools()
                    self._ready.set()
                    reason = await self._wait_for_lifecycle_event()
                    if reason == "reconnect":
                        logger.info(
                            "MCP server '%s': reconnect requested — "
                            "tearing down SSE session", self.name,
                        )
            return

        if _MCP_NEW_HTTP:
            # New API (mcp >= 1.24.0): build an explicit httpx.AsyncClient
            # matching the SDK's own create_mcp_http_client defaults.
            import httpx

            _original_url = httpx.URL(url)

            async def _strip_auth_on_cross_origin_redirect(response):
                """Strip Authorization headers when redirected to a different origin."""
                if response.is_redirect and response.next_request:
                    target = response.next_request.url
                    if (target.scheme, target.host, target.port) != (
                        _original_url.scheme, _original_url.host, _original_url.port,
                    ):
                        response.next_request.headers.pop("authorization", None)
                        response.next_request.headers.pop("Authorization", None)

            client_kwargs: dict = {
                "follow_redirects": True,
                "timeout": httpx.Timeout(float(connect_timeout), read=_SSE_READ_TIMEOUT),
                "verify": ssl_verify,
                "event_hooks": {"response": [_strip_auth_on_cross_origin_redirect]},
            }
            if headers:
                client_kwargs["headers"] = headers
            if _oauth_auth is not None:
                client_kwargs["auth"] = _oauth_auth

            # Caller owns the client lifecycle — the SDK skips cleanup when
            # http_client is provided, so we wrap in async-with.
            async with httpx.AsyncClient(**client_kwargs) as http_client:
                async with streamable_http_client(url, http_client=http_client) as (
                    read_stream, write_stream, _get_session_id,
                ):
                    async with ClientSession(read_stream, write_stream, **sampling_kwargs) as session:
                        self.initialize_result = await session.initialize()
                        self.session = session
                        await self._discover_tools()
                        self._ready.set()
                        reason = await self._wait_for_lifecycle_event()
                        if reason == "reconnect":
                            logger.info(
                                "MCP server '%s': reconnect requested — "
                                "tearing down HTTP session", self.name,
                            )
        else:
            # Deprecated API (mcp < 1.24.0): manages httpx client internally.
            _http_kwargs: dict = {
                "headers": headers,
                "timeout": float(connect_timeout),
                "verify": ssl_verify,
            }
            if _oauth_auth is not None:
                _http_kwargs["auth"] = _oauth_auth
            async with streamablehttp_client(url, **_http_kwargs) as (  # type: ignore[deprecated]
                read_stream, write_stream, _get_session_id,
            ):
                async with ClientSession(read_stream, write_stream, **sampling_kwargs) as session:
                    self.initialize_result = await session.initialize()
                    self.session = session
                    await self._discover_tools()
                    self._ready.set()
                    reason = await self._wait_for_lifecycle_event()
                    if reason == "reconnect":
                        logger.info(
                            "MCP server '%s': reconnect requested — "
                            "tearing down legacy HTTP session", self.name,
                        )

    async def _discover_tools(self):
        """Discover tools from the connected session."""
        if self.session is None:
            return
        async with self._rpc_lock:
            tools_result = await self.session.list_tools()
        self._tools = tools_result.tools
        if self._serving:
            with self.core.setup_admission():
                previous = set(self._registered_tool_names)
                names = _register_server_tools(self.name, self, self._config)
                for name in previous - set(names):
                    self.core.registry.deregister(name)
                self._registered_tool_names = names

    async def run(self, config: dict) -> None:
        """Enter and leave every SDK transport in this one connection task."""
        self._config = config
        self.tool_timeout = config.get("timeout", _DEFAULT_TOOL_TIMEOUT)
        self._auth_type = config.get("auth", "").lower().strip()
        sampling = config.get("sampling", {})
        self._sampling = SamplingHandler(self, sampling) if sampling.get("enabled", True) and _MCP_SAMPLING_TYPES else None
        attempts = 0
        backoff = 1.0
        try:
            while not self._shutdown_event.is_set():
                with self.core.setup_admission():
                    pass
                self._ready.clear()
                try:
                    if self._is_http():
                        await self._run_http(config)
                    else:
                        await self._run_stdio(config)
                    if self._shutdown_event.is_set():
                        return
                    attempts = 0
                    backoff = 1.0
                except Exception as error:
                    if self._shutdown_event.is_set() or self.core.closed:
                        if isinstance(error, ApplicationStoppingError):
                            return
                        # 关闭中的真实传输释放错误不再吞掉。
                        raise
                    if requires_lifecycle_propagation(error) or not _is_retryable_transport_error(error):
                        raise
                    attempts += 1
                    maximum = _MAX_RECONNECT_RETRIES if self._serving else _MAX_INITIAL_CONNECT_RETRIES
                    if attempts > maximum:
                        raise
                    logger.warning("MCP '%s' transport failed; retry %d/%d", self.name, attempts, maximum)
                    try:
                        await asyncio.wait_for(self._shutdown_event.wait(), timeout=backoff)
                    except TimeoutError:
                        pass
                    backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)
                finally:
                    self.session = None
        except ApplicationStoppingError as error:
            self._error = error
            if not self.core.closed and not self._shutdown_event.is_set():
                raise
        except BaseException as error:
            self._error = error
            if self._serving or requires_lifecycle_propagation(error):
                raise
            # 初始连接错误交由明确等待的start请求负责；不把运行期refresh业务失败升格。
        finally:
            self._ready.set()

    async def start(self, config: dict) -> None:
        self._task = self._connection_owner.create(self.run(config), name=f"mcp-server-{self.name}")
        self._task.add_done_callback(self._connection_ended)
        await self._ready.wait()
        if self._error is not None:
            raise self._error
        if self.session is None:
            raise ApplicationStoppingError(f"MCP server '{self.name}' stopped before ready")

    def _connection_ended(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled() and task.exception() is not None:
            self._error = task.exception()
        self._ready.set()

    @property
    def is_idle(self) -> bool:
        return (
            self._connection_owner.is_idle and self._requests.is_idle and self._background.is_idle
            and all(transport.is_idle for transport in self._transports)
            and (self._close_task is None or self._close_task.done())
            and (self._stop_task is None or self._stop_task.done())
        )

    async def stop_calls(self) -> None:
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._stop_requests(), name=f"mcp-stop-{self.name}")
            self._stop_task.add_done_callback(self.core._observe_cleanup)
        await asyncio.shield(self._stop_task)

    async def _stop_requests(self) -> None:
        self._shutdown_event.set()
        await close_resources((
            lambda: self._requests.cancel_and_wait(timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS),
            lambda: self._background.cancel_and_wait(timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS),
        ))

    async def shutdown(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._shutdown(), name=f"mcp-close-{self.name}")
            self._close_task.add_done_callback(self.core._observe_cleanup)
        await asyncio.shield(self._close_task)

    async def _shutdown(self) -> None:
        errors: list[BaseException] = []
        try:
            await self.stop_calls()
        except BaseException as error:
            errors.append(error)
        task = self._task
        if task is not None and not task.done() and self._serving and self.session is not None:
            await asyncio.wait({task}, timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS)
        try:
            # 仅owner发取消，且只取消一次；由连接原task退出AnyIO取消作用域。
            await self._connection_owner.cancel_and_wait(timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS)
        except BaseException as error:
            errors.append(error)
        if task is None or task.done():
            for transport in tuple(self._transports):
                try:
                    await transport.aclose()
                except BaseException as error:
                    errors.append(error)
                if transport.is_idle:
                    self._transports.remove(transport)
        if self._connection_owner.is_idle and self._requests.is_idle and self._background.is_idle:
            for name in tuple(self._registered_tool_names):
                self.core.registry.deregister(name)
            self._registered_tool_names.clear()
            self.session = None
        else:
            errors.append(LifecycleFailure(f"MCP server '{self.name}' is still active"))
        if errors:
            raise BaseExceptionGroup(f"MCP server '{self.name}' cleanup failed", errors)


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

# Runtime server state is owned by MCPCore.
# Circuit breaker: consecutive error counts per server.  After
# MCP_CIRCUIT_BREAKER_THRESHOLD consecutive failures, the handler returns
# a "server unreachable" message that tells the model to stop retrying,
# preventing the 90-iteration burn loop described in #10447.
#
# State machine:
#   closed    — error count below threshold; all calls go through.
#   open      — threshold reached; calls short-circuit until the
#               cooldown elapses.
#   half-open — cooldown elapsed; the next call is a probe that
#               actually hits the session. Probe success → closed.
#               Probe failure → reopens (cooldown re-armed).
#
# ``core.server_breaker_opened_at`` records the monotonic timestamp when
# the breaker most recently transitioned into the open state. Use the
# ``_bump_server_error`` / ``_reset_server_error`` helpers to mutate
# this state — they keep the count and timestamp in sync.
def _bump_server_error(core: MCPCore, server_name: str) -> None:
    """Increment the consecutive-failure count for one core-owned server."""
    with core.lock:
        n = core.server_error_counts.get(server_name, 0) + 1
        core.server_error_counts[server_name] = n
        if n >= MCP_CIRCUIT_BREAKER_THRESHOLD:
            core.server_breaker_opened_at[server_name] = time.monotonic()


def _reset_server_error(core: MCPCore, server_name: str) -> None:
    """Close one core-owned circuit breaker."""
    with core.lock:
        core.server_error_counts[server_name] = 0
        core.server_breaker_opened_at.pop(server_name, None)

# ---------------------------------------------------------------------------
# Auth-failure detection helpers (Task 6 of MCP OAuth consolidation)
# ---------------------------------------------------------------------------

# Cached tuple of auth-related exception types. Lazy so this module
# imports cleanly when the MCP SDK OAuth module is missing.
def _get_auth_error_types() -> tuple:
    """Return a tuple of exception types that indicate MCP OAuth failure.

    Cached after first call. Includes:
      - ``mcp.client.auth.OAuthFlowError`` / ``OAuthTokenError`` — raised by
        the SDK's auth flow when discovery, refresh, or full re-auth fails.
      - ``mcp.client.auth.UnauthorizedError`` (older MCP SDKs) — kept as an
        optional import for forward/backward compatibility.
      - ``tools.mcp_oauth.OAuthNonInteractiveError`` — raised by our callback
        handler when no user is present to complete a browser flow.
      - ``httpx.HTTPStatusError`` — caller must additionally check
        ``status_code == 401`` via :func:`_is_auth_error`.
    """
    types: list = []
    try:
        from mcp.client.auth import OAuthFlowError, OAuthTokenError
        types.extend([OAuthFlowError, OAuthTokenError])
    except ImportError:
        pass
    try:
        # Older MCP SDK variants exported this
        from mcp.client.auth import UnauthorizedError  # type: ignore
        types.append(UnauthorizedError)
    except ImportError:
        pass
    try:
        from .oauth import OAuthNonInteractiveError
        types.append(OAuthNonInteractiveError)
    except ImportError:
        pass
    try:
        import httpx
        types.append(httpx.HTTPStatusError)
    except ImportError:
        pass
    return tuple(types)


def _is_retryable_transport_error(error: BaseException) -> bool:
    if requires_lifecycle_propagation(error):
        return False
    if isinstance(error, BaseExceptionGroup):
        return all(_is_retryable_transport_error(item) for item in error.exceptions)
    import httpx
    import anyio
    return isinstance(error, (
        ConnectionError, TimeoutError, httpx.TransportError,
        anyio.EndOfStream, anyio.BrokenResourceError, anyio.ClosedResourceError,
    ))


def _require_rpc_error(error: BaseException) -> None:
    """Convert only external protocol/transport failures at the tool boundary."""
    if requires_lifecycle_propagation(error):
        raise error
    if _is_retryable_transport_error(error) or _is_auth_error(error):
        return
    from mcp.shared.exceptions import McpError
    import httpx
    if isinstance(error, (McpError, httpx.HTTPStatusError)):
        return
    raise error


def _is_auth_error(exc: BaseException) -> bool:
    """Return True if ``exc`` indicates an MCP OAuth failure.

    ``httpx.HTTPStatusError`` is only treated as auth-related when the
    response status code is 401. Other HTTP errors fall through to the
    generic error path in the tool handlers.
    """
    types = _get_auth_error_types()
    if not types or not isinstance(exc, types):
        return False
    try:
        import httpx
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code == 401
    except ImportError:
        pass
    return True


def _handle_auth_error_and_retry(
    core: MCPCore,
    server_name: str,
    exc: BaseException,
    retry_call,
    op_description: str,
):
    """Attempt auth recovery and one retry; return None to fall through.

    Called by the 5 MCP tool handlers when ``session.<op>()`` raises an
    auth-related exception. Workflow:

      1. Ask :class:`tools.mcp_oauth_manager.MCPOAuthManager.handle_401` if
         recovery is viable (i.e., disk has fresh tokens, or the SDK can
         refresh in-place).
      2. If yes, set the server's ``_reconnect_event`` so the server task
         tears down the current MCP session and rebuilds it with fresh
         credentials. Wait briefly for ``_ready`` to re-fire.
      3. Retry the operation once. Return the retry result if it produced
         a non-error JSON payload. Otherwise return the ``needs_reauth``
         error dict so the model stops hallucinating manual refresh.
      4. Return None if ``exc`` is not an auth error, signalling the
         caller to use the generic error path.

    Args:
        server_name: Name of the MCP server that raised.
        exc: The exception from the failed tool call.
        retry_call: Zero-arg callable that re-runs the tool call, returning
            the same dict format as the handler.
        op_description: Human-readable name of the operation (for logs).

    Returns:
        A dict if auth recovery was attempted, or None to fall
        through to the caller's generic error path.
    """
    if not _is_auth_error(exc):
        return None

    manager = core.oauth_manager

    with core.lock:
        server = core.servers.get(server_name)
    if server is None:
        return None

    async def _recover() -> bool:
        if await manager.handle_401(server_name, None):
            return await server.reconnect()
        return False

    try:
        recovered = _run_on_mcp_loop(core, _recover, timeout=15, server=server)
    except Exception as rec_exc:
        _require_rpc_error(rec_exc)
        recovered = False

    if recovered:
        # A successful OAuth recovery is independent evidence that the
        # server is viable again, so close the circuit breaker here —
        # not only on retry success. Without this, a reconnect
        # followed by a failing retry would leave the breaker pinned
        # above threshold forever (the retry-exception branch below
        # bumps the count again).  The post-reset retry still goes
        # through _bump_server_error on failure, so a genuinely broken
        # server will re-trip the breaker as normal.
        _reset_server_error(core, server_name)

        try:
            result = retry_call()
            if not isinstance(result, dict) or "error" not in result:
                _reset_server_error(core, server_name)
                return result
        except Exception as retry_exc:
            _require_rpc_error(retry_exc)
            logger.warning(
                "MCP %s/%s retry after auth recovery failed: %s",
                server_name, op_description, retry_exc,
            )

    # No recovery available, or retry also failed: surface a structured
    # needs_reauth error. Bumps the circuit breaker so the model stops
    # retrying the tool.
    _bump_server_error(core, server_name)
    return {
        "error": (
            f"MCP server '{server_name}' requires re-authentication. "
            f"Delete the tokens file under agentspace/mcp-tokens/ and "
            f"restart the agent. Do NOT retry this tool — ask the user "
            f"to re-authenticate."
        ),
        "needs_reauth": True,
        "server": server_name,
    }


# Substrings (lower-cased match) that indicate the MCP server rejected
# the request because its server-side transport session expired /
# was garbage-collected.  The caller's OAuth token is still valid —
# only the transport-layer session state needs rebuilding.  See #13383.
_SESSION_EXPIRED_MARKERS: tuple = (
    "invalid or expired session",
    "expired session",
    "session expired",
    "session not found",
    "unknown session",
    "session terminated",
    "closedresourceerror",
    "closed resource",
    "transport is closed",
    "connection closed",
    "broken pipe",
    "end of file",
)


def _is_session_expired_error(exc: BaseException) -> bool:
    """Return True if ``exc`` looks like an MCP transport session expiry.

    Streamable HTTP MCP servers may garbage-collect server-side session
    state while the OAuth token remains valid — idle TTL, server
    restart, horizontal-scaling pod rotation, etc.  The SDK surfaces
    this as a JSON-RPC error whose message contains phrases like
    ``"Invalid or expired session"``.  This class of failure is
    distinct from :func:`_is_auth_error`: re-running the OAuth refresh
    flow would be pointless because the access token is fine.  What's
    needed is a transport reconnect — tear down and rebuild the
    ``streamablehttp_client`` + ``ClientSession`` pair, which is
    exactly what ``MCPServerTask._reconnect_event`` triggers.
    """
    if isinstance(exc, InterruptedError):
        return False
    # Exception messages vary across SDK versions + server
    # implementations, so match on a small allow-list of stable
    # substrings rather than exception type.  Kept narrow to avoid
    # false positives on unrelated server errors.
    msg = str(exc).lower()
    if not msg:
        return False
    return any(marker in msg for marker in _SESSION_EXPIRED_MARKERS)


def _handle_session_expired_and_retry(
    core: MCPCore,
    server_name: str,
    exc: BaseException,
    retry_call,
    op_description: str,
):
    """Trigger a transport reconnect and retry once on session expiry.

    Unlike :func:`_handle_auth_error_and_retry`, this does **not** call
    the OAuth manager's ``handle_401`` — the access token is still
    valid, only the server-side session state is stale.  Setting
    ``_reconnect_event`` causes the server task's lifecycle loop to
    tear down the current ``streamablehttp_client`` + ``ClientSession``
    and rebuild them, reusing the existing OAuth provider instance.
    See #13383.

    Args:
        server_name: Name of the MCP server that raised.
        exc: The exception from the failed call.
        retry_call: Zero-arg callable that re-runs the operation,
            returning the same dict format as the handler.
        op_description: Human-readable name of the operation (logs).

    Returns:
        A dict if reconnect + retry was attempted and produced
        a response, or ``None`` to fall through to the caller's
        generic error path (not a session-expired error, no server
        record, reconnect didn't ready in time, or retry also failed).
    """
    if not _is_session_expired_error(exc):
        return None

    with core.lock:
        srv = core.servers.get(server_name)
    if srv is None:
        return None
    try:
        ready = _run_on_mcp_loop(core, srv.reconnect, timeout=15, server=srv)
    except Exception as reconnect_error:
        _require_rpc_error(reconnect_error)
        return None
    if not ready:
        return None

    try:
        result = retry_call()
        if not isinstance(result, dict) or "error" not in result:
            _reset_server_error(core, server_name)
            return result
    except Exception as retry_exc:
        _require_rpc_error(retry_exc)
        logger.warning(
            "MCP %s/%s retry after session reconnect failed: %s",
            server_name, op_description, retry_exc,
        )
    return None


# MCP transport loops, locks, stderr handles, and child PID registries are
# owned by MCPCore instances. SDK availability flags are immutable capability
# metadata rather than runtime state.



def _run_on_mcp_loop(
    core: MCPCore, factory: Callable[[], Coroutine[Any, Any, Any]],
    timeout: float = 30, *, server: MCPServerTask | None = None,
) -> Any:
    return core.call(
        factory, timeout=timeout,
        owner=None if server is None else server._requests,
        admission=None if server is None else server._admit_request,
    )



def _interrupted_call_result() -> dict:
    """Standardized error dict for a user-interrupted MCP tool call."""
    return {
        "error": "MCP call interrupted: user sent a new message"
    }


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _interpolate_env_vars(value):
    """Recursively resolve ``${VAR}`` placeholders from ``os.environ``."""
    if isinstance(value, str):
        def _replace(m):
            return os.environ.get(m.group(1), m.group(0))
        return _ENV_VAR_PATTERN.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _interpolate_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_env_vars(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Server connection helper
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Handler / check-fn factories
# ---------------------------------------------------------------------------

def _make_tool_handler(core: MCPCore, server_name: str, tool_name: str, tool_timeout: float):
    """Return a sync handler that calls an MCP tool via the background loop.

    The handler conforms to the registry's dispatch interface:
    ``handler(args_dict, **kwargs) -> dict``
    """

    def _handler(args: dict, **_kwargs) -> dict:
        # Strip framework-internal keys (injected upstream by the tool
        # executor and the approval executor) before handing arguments to
        # the external MCP server. Strict servers validate against their
        # input schema with additionalProperties: false and reject unknown
        # properties, so leaking these keys breaks every call. Built-in
        # tools are unaffected: their handlers read these keys directly,
        # and this stripping lives only on the MCP dispatch path.
        args = {k: v for k, v in args.items() if k not in TOOL_INTERNAL_ARG_KEYS}
        with core.admission():
            pass
        # Circuit breaker: if this server has failed too many times
        # consecutively, short-circuit with a clear message so the model
        # stops retrying and uses alternative approaches (#10447).
        #
        # Once the cooldown elapses, the breaker transitions to
        # half-open: we let the *next* call through as a probe. On
        # success the success-path below resets the breaker; on
        # failure the error paths below bump the count again, which
        # re-stamps the open-time via _bump_server_error (re-arming
        # the cooldown).
        with core.lock:
            error_count = core.server_error_counts.get(server_name, 0)
            opened_at = core.server_breaker_opened_at.get(server_name, 0.0)
        if error_count >= MCP_CIRCUIT_BREAKER_THRESHOLD:
            age = time.monotonic() - opened_at
            if age < MCP_CIRCUIT_BREAKER_COOLDOWN_SECONDS:
                remaining = max(1, int(MCP_CIRCUIT_BREAKER_COOLDOWN_SECONDS - age))
                return {
                    "error": (
                        f"MCP server '{server_name}' is unreachable after "
                        f"{error_count} consecutive "
                        f"failures. Auto-retry available in ~{remaining}s. "
                        f"Do NOT retry this tool yet — use alternative "
                        f"approaches or ask the user to check the MCP server."
                    )
                }
            # Cooldown elapsed → fall through as a half-open probe.

        with core.lock:
            server = core.servers.get(server_name)
        if not server or not server.session:
            _bump_server_error(core, server_name)
            return {
                "error": f"MCP server '{server_name}' is not connected"
            }

        async def _call():
            async with server._rpc_lock:
                result = await server.require_session().call_tool(tool_name, arguments=args)
            # MCP CallToolResult has .content (list of content blocks) and .isError
            if result.isError:
                error_text = ""
                for block in (result.content or []):
                    if isinstance(block, TextContent):
                        error_text += block.text
                return {
                    "error": _sanitize_error(
                        error_text or "MCP tool returned an error"
                    )
                }

            # Collect text from content blocks. MCP tool results can also
            # include ImageContent blocks (screenshot / Blockbench / Playwright
            # etc.); cache those via the gateway's image-cache helper so they
            # flow through the agent's MEDIA: tag convention and out to messaging
            # adapters that render images natively. Without this, image blocks
            # were silently dropped and the agent got an empty response.
            #
            # Distilled from #17915 (c3115644151) and #10848 (gnanirahulnutakki),
            # both too stale to cherry-pick. #10848's approach (integrate with
            # the MEDIA tag + cache_image_from_bytes) was the cleaner of
            # the two — plugs into existing infrastructure.
            parts: list[str] = []
            for block in (result.content or []):
                if isinstance(block, TextContent) and block.text:
                    parts.append(block.text)
            text_result = "\n".join(parts) if parts else ""

            # Combine content + structuredContent when both are present.
            # MCP spec: content is model-oriented (text), structuredContent
            # is machine-oriented (JSON metadata).  For an AI agent, content
            # is the primary payload; structuredContent supplements it.
            structured = result.structuredContent
            if structured is not None:
                if text_result:
                    return {
                        "result": text_result,
                        "structuredContent": structured,
                    }
                return {"result": structured}
            return {"result": text_result}

        def _call_once():
            return _run_on_mcp_loop(core, _call, timeout=tool_timeout, server=server)

        try:
            result = _call_once()
            # Check if the MCP tool itself returned an error
            if isinstance(result, dict) and "error" in result:
                _bump_server_error(core, server_name)
            else:
                _reset_server_error(core, server_name)  # success — reset
            return result
        except InterruptedError:
            return _interrupted_call_result()
        except Exception as exc:
            _require_rpc_error(exc)
            # Auth-specific recovery path: consult the manager, signal
            # reconnect if viable, retry once. Returns None to fall
            # through for non-auth exceptions.
            recovered = _handle_auth_error_and_retry(
                core, server_name, exc, _call_once,
                f"tools/call {tool_name}",
            )
            if recovered is not None:
                return recovered

            # Transport session expiry (#13383): same reconnect flow
            # but skips OAuth recovery because the access token is
            # still valid — only the server-side session is stale.
            recovered = _handle_session_expired_and_retry(
                core, server_name, exc, _call_once,
                f"tools/call {tool_name}",
            )
            if recovered is not None:
                return recovered

            _bump_server_error(core, server_name)
            logger.error(
                "MCP tool %s/%s call failed: %s",
                server_name, tool_name, exc,
            )
            return {
                "error": _sanitize_error(
                    f"MCP call failed: {type(exc).__name__}: {_exc_str(exc)}"
                )
            }

    return _handler


def _make_list_resources_handler(core: MCPCore, server_name: str, tool_timeout: float):
    """Return a sync handler that lists resources from an MCP server."""

    def _handler(_args: dict, **_kwargs) -> dict:
        with core.admission():
            pass
        with core.lock:
            server = core.servers.get(server_name)
        if not server or not server.session:
            return {
                "error": f"MCP server '{server_name}' is not connected"
            }

        async def _call():
            async with server._rpc_lock:
                result = await server.require_session().list_resources()
            resources = []
            for r in result.resources:
                entry = {"uri": str(r.uri), "name": r.name}
                if r.description:
                    entry["description"] = r.description
                if r.mimeType:
                    entry["mimeType"] = r.mimeType
                resources.append(entry)
            return {"resources": resources}

        def _call_once():
            return _run_on_mcp_loop(core, _call, timeout=tool_timeout, server=server)

        try:
            return _call_once()
        except InterruptedError:
            return _interrupted_call_result()
        except Exception as exc:
            _require_rpc_error(exc)
            recovered = _handle_auth_error_and_retry(
                core, server_name, exc, _call_once, "resources/list",
            )
            if recovered is not None:
                return recovered
            recovered = _handle_session_expired_and_retry(
                core, server_name, exc, _call_once, "resources/list",
            )
            if recovered is not None:
                return recovered
            logger.error(
                "MCP %s/list_resources failed: %s", server_name, exc,
            )
            return {
                "error": _sanitize_error(
                    f"MCP call failed: {type(exc).__name__}: {_exc_str(exc)}"
                )
            }

    return _handler


def _make_read_resource_handler(core: MCPCore, server_name: str, tool_timeout: float):
    """Return a sync handler that reads a resource by URI from an MCP server."""

    def _handler(args: dict, **_kwargs) -> dict:
        with core.admission():
            pass
        with core.lock:
            server = core.servers.get(server_name)
        if not server or not server.session:
            return {
                "error": f"MCP server '{server_name}' is not connected"
            }

        uri = args.get("uri")
        if not uri:
            return {"error": f"Missing required parameter 'uri'"}

        async def _call():
            async with server._rpc_lock:
                result = await server.require_session().read_resource(uri)
            # read_resource returns ReadResourceResult with .contents list
            parts: list[str] = []
            for block in result.contents:
                if isinstance(block, TextResourceContents):
                    parts.append(block.text)
                elif isinstance(block, BlobResourceContents):
                    parts.append(f"[binary data, {len(block.blob)} bytes]")
            return {"result": "\n".join(parts) if parts else ""}

        def _call_once():
            return _run_on_mcp_loop(core, _call, timeout=tool_timeout, server=server)

        try:
            return _call_once()
        except InterruptedError:
            return _interrupted_call_result()
        except Exception as exc:
            _require_rpc_error(exc)
            recovered = _handle_auth_error_and_retry(
                core, server_name, exc, _call_once, "resources/read",
            )
            if recovered is not None:
                return recovered
            recovered = _handle_session_expired_and_retry(
                core, server_name, exc, _call_once, "resources/read",
            )
            if recovered is not None:
                return recovered
            logger.error(
                "MCP %s/read_resource failed: %s", server_name, exc,
            )
            return {
                "error": _sanitize_error(
                    f"MCP call failed: {type(exc).__name__}: {_exc_str(exc)}"
                )
            }

    return _handler


def _make_list_prompts_handler(core: MCPCore, server_name: str, tool_timeout: float):
    """Return a sync handler that lists prompts from an MCP server."""

    def _handler(_args: dict, **_kwargs) -> dict:
        with core.admission():
            pass
        with core.lock:
            server = core.servers.get(server_name)
        if not server or not server.session:
            return {
                "error": f"MCP server '{server_name}' is not connected"
            }

        async def _call():
            async with server._rpc_lock:
                result = await server.require_session().list_prompts()
            prompts = []
            for p in result.prompts:
                entry = {"name": p.name}
                if p.description:
                    entry["description"] = p.description
                if p.arguments:
                    entry["arguments"] = [
                        {
                            "name": a.name,
                            **({"description": a.description} if a.description else {}),
                            "required": a.required,
                        }
                        for a in p.arguments
                    ]
                prompts.append(entry)
            return {"prompts": prompts}

        def _call_once():
            return _run_on_mcp_loop(core, _call, timeout=tool_timeout, server=server)

        try:
            return _call_once()
        except InterruptedError:
            return _interrupted_call_result()
        except Exception as exc:
            _require_rpc_error(exc)
            recovered = _handle_auth_error_and_retry(
                core, server_name, exc, _call_once, "prompts/list",
            )
            if recovered is not None:
                return recovered
            recovered = _handle_session_expired_and_retry(
                core, server_name, exc, _call_once, "prompts/list",
            )
            if recovered is not None:
                return recovered
            logger.error(
                "MCP %s/list_prompts failed: %s", server_name, exc,
            )
            return {
                "error": _sanitize_error(
                    f"MCP call failed: {type(exc).__name__}: {_exc_str(exc)}"
                )
            }

    return _handler


def _make_get_prompt_handler(core: MCPCore, server_name: str, tool_timeout: float):
    """Return a sync handler that gets a prompt by name from an MCP server."""

    def _handler(args: dict, **_kwargs) -> dict:
        with core.admission():
            pass
        with core.lock:
            server = core.servers.get(server_name)
        if not server or not server.session:
            return {
                "error": f"MCP server '{server_name}' is not connected"
            }

        name = args.get("name")
        if not name:
            return {"error": f"Missing required parameter 'name'"}
        arguments = args.get("arguments", {})

        async def _call():
            async with server._rpc_lock:
                result = await server.require_session().get_prompt(name, arguments=arguments)
            # GetPromptResult has .messages list
            messages = []
            for msg in result.messages:
                content = msg.content
                entry = {"role": msg.role}
                entry["content"] = content.text if isinstance(content, TextContent) else str(content)
                messages.append(entry)
            resp = {"messages": messages}
            if result.description:
                resp["description"] = result.description
            return resp

        def _call_once():
            return _run_on_mcp_loop(core, _call, timeout=tool_timeout, server=server)

        try:
            return _call_once()
        except InterruptedError:
            return _interrupted_call_result()
        except Exception as exc:
            _require_rpc_error(exc)
            recovered = _handle_auth_error_and_retry(
                core, server_name, exc, _call_once, "prompts/get",
            )
            if recovered is not None:
                return recovered
            recovered = _handle_session_expired_and_retry(
                core, server_name, exc, _call_once, "prompts/get",
            )
            if recovered is not None:
                return recovered
            logger.error(
                "MCP %s/get_prompt failed: %s", server_name, exc,
            )
            return {
                "error": _sanitize_error(
                    f"MCP call failed: {type(exc).__name__}: {_exc_str(exc)}"
                )
            }

    return _handler


def _make_check_fn(core: MCPCore, server_name: str):
    """Return a check function that verifies the MCP connection is alive."""

    def _check() -> bool:
        with core.lock:
            server = core.servers.get(server_name)
        return server is not None and server.session is not None

    return _check


# ---------------------------------------------------------------------------
# Discovery & registration
# ---------------------------------------------------------------------------

def _normalize_mcp_input_schema(schema: dict | None) -> dict:
    """Compatibility wrapper for the shared MCP schema normalizer.

    The historical private entry point remains available for callers and
    tests that import it from this module. The implementation lives in
    ``abstract.mcp.schema`` so discovery and sampling share one walker.
    """
    return _normalize_schema(
        schema,
        diagnostic=lambda path, code: logger.debug(
            "MCP schema normalized at %s (%s)", path, code
        ),
    )


def sanitize_mcp_name_component(value: str) -> str:
    """Return an MCP name component safe for tool and prefix generation.

    Preserves the historical behavior of converting hyphens to
    underscores, and also replaces any other character outside
    ``[A-Za-z0-9_]`` with ``_`` so generated tool names are compatible with
    provider validation rules.
    """
    return re.sub(r"[^A-Za-z0-9_]", "_", str(value or ""))


def _convert_mcp_schema(server_name: str, mcp_tool) -> dict:
    """Convert an MCP tool listing to the agent's registry schema format.

    Args:
        server_name: The logical server name for prefixing.
        mcp_tool:    An MCP ``Tool`` object with ``.name``, ``.description``,
                     and ``.inputSchema``.

    Returns:
        A dict suitable for ``registry.register(schema=...)``.
    """
    safe_tool_name = sanitize_mcp_name_component(mcp_tool.name)
    safe_server_name = sanitize_mcp_name_component(server_name)
    prefixed_name = f"mcp_{safe_server_name}_{safe_tool_name}"
    return {
        "name": prefixed_name,
        "description": mcp_tool.description or f"MCP tool {mcp_tool.name} from {server_name}",
        "parameters": _normalize_mcp_input_schema(mcp_tool.inputSchema),
    }


def _build_utility_schemas(server_name: str) -> list[dict]:
    """Build schemas for the MCP utility tools (resources & prompts).

    Returns a list of (schema, handler_factory_name) tuples encoded as dicts
    with keys: schema, handler_key.
    """
    safe_name = sanitize_mcp_name_component(server_name)
    return [
        {
            "schema": {
                "name": f"mcp_{safe_name}_list_resources",
                "description": f"List available resources from MCP server '{server_name}'",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
            "handler_key": "list_resources",
        },
        {
            "schema": {
                "name": f"mcp_{safe_name}_read_resource",
                "description": f"Read a resource by URI from MCP server '{server_name}'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "uri": {
                            "type": "string",
                            "description": "URI of the resource to read",
                        },
                    },
                    "required": ["uri"],
                },
            },
            "handler_key": "read_resource",
        },
        {
            "schema": {
                "name": f"mcp_{safe_name}_list_prompts",
                "description": f"List available prompts from MCP server '{server_name}'",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
            "handler_key": "list_prompts",
        },
        {
            "schema": {
                "name": f"mcp_{safe_name}_get_prompt",
                "description": f"Get a prompt by name from MCP server '{server_name}'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name of the prompt to retrieve",
                        },
                        "arguments": {
                            "type": "object",
                            "description": "Optional arguments to pass to the prompt",
                            "properties": {},
                            "additionalProperties": True,
                        },
                    },
                    "required": ["name"],
                },
            },
            "handler_key": "get_prompt",
        },
    ]


def _normalize_name_filter(value: str | list[str] | tuple[str, ...] | set[str] | None, label: str) -> set[str]:
    """Normalize include/exclude config to a set of tool names."""
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    if isinstance(value, (list, tuple, set)):
        return {str(item) for item in value}
    logger.warning("MCP config %s must be a string or list of strings; ignoring %r", label, value)
    return set()


_UTILITY_CAPABILITY_METHODS = {
    "list_resources": "list_resources",
    "read_resource": "read_resource",
    "list_prompts": "list_prompts",
    "get_prompt": "get_prompt",
}

# Maps each utility handler to the MCP capability key that must be non-None
# on the server's ``initialize`` response for the handler to be registered.
# Source of truth: MCP spec — capabilities.resources / capabilities.prompts
# are present on the response only when the server actually implements
# those request families. Without this gate, tools-only servers (e.g.
# Context7 @upstash/context7-mcp, which advertises only ``tools``) had
# all four utility stubs registered and every model call to them came
# back with JSON-RPC ``-32601 Method not found``, which made the model
# conclude the server was broken even when the real tools worked. See
# #18051.
_UTILITY_CAPABILITY_ATTRS = {
    "list_resources": "resources",
    "read_resource": "resources",
    "list_prompts": "prompts",
    "get_prompt": "prompts",
}


def _select_utility_schemas(server_name: str, server: MCPServerTask, config: dict) -> list[dict]:
    """Select utility schemas based on config and server capabilities."""
    tools_filter = config.get("tools") or {}
    resources_enabled = as_bool(tools_filter.get("resources"), default=True)
    prompts_enabled = as_bool(tools_filter.get("prompts"), default=True)

    # ``initialize_result.capabilities`` is the source of truth: its sub-objects
    # (``resources``, ``prompts``) are non-None iff the server advertises that
    # request family. ``hasattr(server.session, ...)`` was the old gate but
    # ClientSession always has the four method attributes defined on the class,
    # so it never filtered anything.
    init_result = server.initialize_result
    if init_result is None:
        raise LifecycleFailure("MCP capabilities are unavailable before initialization")
    advertised_caps = init_result.capabilities

    selected: list[dict] = []
    for entry in _build_utility_schemas(server_name):
        handler_key = entry["handler_key"]
        if handler_key in {"list_resources", "read_resource"} and not resources_enabled:
            logger.debug("MCP server '%s': skipping utility '%s' (resources disabled)", server_name, handler_key)
            continue
        if handler_key in {"list_prompts", "get_prompt"} and not prompts_enabled:
            logger.debug("MCP server '%s': skipping utility '%s' (prompts disabled)", server_name, handler_key)
            continue

        if handler_key in ("list_resources", "read_resource"):
            if advertised_caps.resources is None:
                continue
        elif advertised_caps.prompts is None:
            continue
        selected.append(entry)
    return selected


def _existing_tool_names(core: MCPCore) -> list[str]:
    """Return tool names for all currently connected servers."""
    names: list[str] = []
    for _sname, server in core.servers.items():
        names.extend(server._registered_tool_names)
    return names


def _register_server_tools(name: str, server: MCPServerTask, config: dict) -> list[str]:
    """Register tools from an already-connected server into the registry.

    Handles include/exclude filtering and utility tools. Toolset resolution
    for ``mcp-{server}`` and raw server-name aliases is derived from the live
    registry, rather than mutating ``toolsets.TOOLSETS`` at runtime.

    Used by both initial discovery and dynamic refresh (list_changed).

    Returns:
        List of registered prefixed tool names.
    """
    registry = server.core.registry
    core = server.core

    registered_names: list[str] = []
    toolset_name = f"mcp-{name}"

    # Selective tool loading: honour include/exclude lists from config.
    # Rules (matching issue #690 spec):
    #   tools.include — whitelist: only these tool names are registered
    #   tools.exclude — blacklist: all tools EXCEPT these are registered
    #   include takes precedence over exclude
    #   Neither set → register all tools (backward-compatible default)
    tools_filter = config.get("tools") or {}
    include_set = _normalize_name_filter(tools_filter.get("include"), f"mcp_servers.{name}.tools.include")
    exclude_set = _normalize_name_filter(tools_filter.get("exclude"), f"mcp_servers.{name}.tools.exclude")

    def _should_register(tool_name: str) -> bool:
        if include_set:
            return tool_name in include_set
        if exclude_set:
            return tool_name not in exclude_set
        return True

    for mcp_tool in server._tools:
        if not _should_register(mcp_tool.name):
            logger.debug("MCP server '%s': skipping tool '%s' (filtered by config)", name, mcp_tool.name)
            continue

        # Scan tool description for prompt injection patterns
        _scan_mcp_description(name, mcp_tool.name, mcp_tool.description or "")

        schema = _convert_mcp_schema(name, mcp_tool)
        tool_name_prefixed = schema["name"]

        # Guard against collisions with built-in (non-MCP) tools.
        existing_toolset = registry.get_toolset_for_tool(tool_name_prefixed)
        if existing_toolset is not None and existing_toolset != toolset_name:
            raise ValueError(f"MCP tool name collision: {tool_name_prefixed} belongs to {existing_toolset}")

        registry.register(
            name=tool_name_prefixed,
            toolset=toolset_name,
            schema=schema,
            handler=_make_tool_handler(core, name, mcp_tool.name, server.tool_timeout),
            check_fn=_make_check_fn(core, name),
            is_async=False,
            description=schema["description"],
        )
        registered_names.append(tool_name_prefixed)
        if tool_name_prefixed not in server._registered_tool_names:
            server._registered_tool_names.append(tool_name_prefixed)

    # Register MCP Resources & Prompts utility tools, filtered by config and
    # only when the server actually supports the corresponding capability.
    _handler_factories = {
        "list_resources": lambda server_name, timeout: _make_list_resources_handler(core, server_name, timeout),
        "read_resource": lambda server_name, timeout: _make_read_resource_handler(core, server_name, timeout),
        "list_prompts": lambda server_name, timeout: _make_list_prompts_handler(core, server_name, timeout),
        "get_prompt": lambda server_name, timeout: _make_get_prompt_handler(core, server_name, timeout),
    }
    check_fn = _make_check_fn(core, name)
    for entry in _select_utility_schemas(name, server, config):
        schema = entry["schema"]
        handler_key = entry["handler_key"]
        handler = _handler_factories[handler_key](name, server.tool_timeout)
        util_name = schema["name"]

        # Same collision guard for utility tools.
        existing_toolset = registry.get_toolset_for_tool(util_name)
        if existing_toolset is not None and existing_toolset != toolset_name:
            raise ValueError(f"MCP utility name collision: {util_name} belongs to {existing_toolset}")

        registry.register(
            name=util_name,
            toolset=toolset_name,
            schema=schema,
            handler=handler,
            check_fn=check_fn,
            is_async=False,
            description=schema["description"],
        )
        registered_names.append(util_name)
        if util_name not in server._registered_tool_names:
            server._registered_tool_names.append(util_name)

    registry.register_toolset(name=toolset_name, description=f"MCP server: {name}")
    if registered_names:
        registry.register_toolset_alias(name, toolset_name)

    return registered_names


async def _discover_and_register_server(
    name: str, config: dict, core: MCPCore,
) -> list[str]:
    """Connect to a single MCP server, discover tools, and register them.

    Returns list of registered tool names.
    """
    server = MCPServerTask(name, core)
    with core.setup_admission():
        if name in core.servers:
            raise LifecycleFailure(f"MCP server already exists: {name}")
        core.servers[name] = server
    try:
        async with asyncio.timeout(config.get("connect_timeout", _DEFAULT_CONNECT_TIMEOUT)):
            await server.start(config)
        with core.setup_admission():
            registered_names = _register_server_tools(name, server, config)
            server._registered_tool_names = list(registered_names)
            server._serving = True
            server._registered.set()
    except BaseException as original:
        try:
            await server.shutdown()
        except BaseException as cleanup:
            raise BaseExceptionGroup("MCP connect and cleanup failed", [original, cleanup])
        with core.lock:
            core.servers.pop(name, None)
        raise

    transport_type = "HTTP" if "url" in config else "stdio"
    logger.info(
        "MCP server '%s' (%s): registered %d tool(s): %s",
        name, transport_type, len(registered_names),
        ", ".join(registered_names),
    )
    return registered_names


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_mcp_status(core) -> list[dict]:
    """Return status of all connected MCP servers for banner display.

    Returns a list of dicts with keys: name, transport, tools, connected.
    Registered and connecting servers are owned by the supplied MCPCore.
    """
    result: list[dict] = []

    with core.lock:
        active_servers = dict(core.servers)

    for name, server in active_servers.items():
        transport = "http" if server._is_http() else "stdio"
        if server.session is not None:
            entry = {
                "name": name,
                "transport": transport,
                "tools": len(server._registered_tool_names),
                "connected": True,
            }
            if server._sampling:
                entry["sampling"] = dict(server._sampling.metrics)
            result.append(entry)
        else:
            result.append({
                "name": name,
                "transport": transport,
                "tools": 0,
                "connected": False,
            })

    return result


def _stop_mcp_loop(core: MCPCore) -> None:
    """Release loop handles only after its real thread has been joined."""
    with core.lock:
        if any(not future.done() for future in core._control_futures):
            raise LifecycleFailure("MCP cleanup handoffs are still active")
        loop = core.mcp_loop
        thread = core.mcp_thread
    if loop is not None:
        if loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=SYSTEM_QUIESCE_TIMEOUT_SECONDS)
            if thread.is_alive():
                raise LifecycleFailure("MCP event loop thread did not stop")
        loop.close()
        with core.lock:
            core.mcp_loop = None
            core.mcp_thread = None
