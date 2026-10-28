"""唯一运行时系统：配置、输入接收同步边界与进程关闭请求。"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
import logging
import os
import sys
import threading
from pathlib import Path

from interface.runtime_system import IRuntimeSystem

from entity.constant import (
    AGENT_LOOP_SETTINGS_ES_FILENAME,
    APPLICATION_SHUTDOWN_TIMEOUT_SECONDS,
    ApplicationState,
    DEFAULT_MAIN_AGENT_CHARACTER_NAME,
    EXIT_EVOLVED,
    EXIT_FAILURE,
    EXIT_NORMAL,
    SOUL_META_CHARACTER_NAME_KEY,
    ShutdownReason,
)
from entity.puretype.agent_settings import AgentLoopSettingsState
from system.agent_loop_settings import AgentLoopSettingsStore
from system.cleanup_errors import split_cleanup_timeouts
from system.context import RuntimeContext
from system.lifecycle import ApplicationStoppingError, LifecycleFailure
from system.resource_cleanup import ResourceCleanupRegistry

logger = logging.getLogger(__name__)


def _read_main_agent_character_name_from_soul_meta(meta_path:Path) -> str:
    """从 SOUL.md.meta 读取主Agent角色名。

    文件不存在、无 [character_name] 键或解析失败时回退默认角色名。
    解析失败属于配置错误，仅记 warning 不阻断启动（Fail-Soft 仅限该边界）。
    """
    import logging
    from util.file_metadata import MetaFormatError, parse_meta_content

    logger = logging.getLogger(__name__)
    if not meta_path.is_file():
        return DEFAULT_MAIN_AGENT_CHARACTER_NAME
    try:
        content = meta_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to read %s: %s; falling back to default main agent name", meta_path, exc)
        return DEFAULT_MAIN_AGENT_CHARACTER_NAME
    try:
        metadata = parse_meta_content(content)
    except MetaFormatError as exc:
        logger.warning("Invalid %s: %s; falling back to default main agent name", meta_path, exc)
        return DEFAULT_MAIN_AGENT_CHARACTER_NAME
    name = metadata.get(SOUL_META_CHARACTER_NAME_KEY, "").strip()
    return name if name else DEFAULT_MAIN_AGENT_CHARACTER_NAME


def _resolve_soul_meta_path(agentspace, soul_file: str) -> Path:
    """根据当前 SOUL 文件名推导对应 .meta 文件路径。"""
    from pathlib import Path
    from entity.constant import META_FILE_SUFFIX
    return Path(agentspace) / f"{soul_file}{META_FILE_SUFFIX}"


class RuntimeSystem(IRuntimeSystem):
    """所有业务接收与关闭请求共享同一把进程内锁。"""

    def __init__(self, ctx: RuntimeContext) -> None:
        super().__init__()
        self._context = ctx
        self._lock = threading.RLock()
        self._state = ApplicationState.NEW
        self._loop: asyncio.AbstractEventLoop | None = None
        self._shutdown_event: asyncio.Event | None = None
        self._shutdown_reason: ShutdownReason | None = None
        self._failures: list[BaseException] = []
        self._reported_failure_objects: list[BaseException] = []
        self._cleanup = ResourceCleanupRegistry(self.record_failure)
        self._agent_loop_settings: AgentLoopSettingsStore | None = None
        self._input_sequence = 0
        self._shutdown_deadline: threading.Timer | None = None
        # 主Agent角色名：启动时从 SOUL.md.meta 读取一次；运行期由 RefreshIdentity 工具刷新。
        # 默认使用 DEFAULT_MAIN_AGENT_CHARACTER_NAME 作为回退。
        self._main_agent_character_name: str = DEFAULT_MAIN_AGENT_CHARACTER_NAME

    async def virtual_awake(self) -> None:
        with self._lock:
            if self._loop is not None:
                raise LifecycleFailure("RuntimeSystem cannot be initialized twice")
            self._loop = asyncio.get_running_loop()
            self._shutdown_event = asyncio.Event()
            if self._state == ApplicationState.NEW:
                self._state = ApplicationState.STARTING
            elif self._state == ApplicationState.STOPPING:
                self._shutdown_event.set()
            else:
                raise LifecycleFailure(f"Invalid runtime initialization state: {self._state}")
        self._agent_loop_settings = AgentLoopSettingsStore(
            self._context.workspace / AGENT_LOOP_SETTINGS_ES_FILENAME,
        )
        self._agent_loop_settings.initialize()
        # 启动时读取一次主Agent角色名（SOUL.md.meta），此后由 RefreshIdentity 工具按需刷新。
        self.refresh_main_agent_character_name()

    @property
    def cleanup(self) -> ResourceCleanupRegistry:
        return self._cleanup

    @property
    def context(self) -> RuntimeContext:
        return self._context

    def _require_agent_loop_settings(self) -> AgentLoopSettingsStore:
        if self._agent_loop_settings is None:
            raise LifecycleFailure("Agent loop settings have not been initialized")
        return self._agent_loop_settings

    @property
    def max_tool_turns(self) -> int:
        return self._require_agent_loop_settings().max_tool_turns

    def get_agent_loop_settings(self) -> AgentLoopSettingsState:
        return self._require_agent_loop_settings().get_state()

    def set_max_tool_turns(self, value: int | None) -> AgentLoopSettingsState:
        self.require_running()
        return self._require_agent_loop_settings().set_max_tool_turns(value)

    @property
    def main_agent_character_name(self) -> str:
        """返回当前主Agent角色名（启动时初始化，可由 RefreshIdentity 工具刷新）。"""
        with self._lock:
            return self._main_agent_character_name

    def refresh_main_agent_character_name(self, soul_file: str = "SOUL.md") -> str:
        """从 agentspace/{soul_file}.meta 重新读取主Agent角色名。

        由 RefreshIdentity 工具调用；返回刷新后的名字。
        """
        meta_path = _resolve_soul_meta_path(self._context.agentspace, soul_file)
        name = _read_main_agent_character_name_from_soul_meta(meta_path)
        with self._lock:
            self._main_agent_character_name = name
        return name

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            raise LifecycleFailure("RuntimeSystem event loop has not been bound")
        return self._loop

    @property
    def state(self) -> ApplicationState:
        with self._lock:
            return self._state

    @property
    def shutdown_event(self) -> asyncio.Event:
        if self._shutdown_event is None:
            raise LifecycleFailure("RuntimeSystem shutdown event has not been initialized")
        return self._shutdown_event

    @property
    def shutdown_reason(self) -> ShutdownReason | None:
        with self._lock:
            return self._shutdown_reason

    @property
    def failures(self) -> tuple[BaseException, ...]:
        with self._lock:
            return tuple(self._failures)

    @property
    def exit_code(self) -> int:
        """失败永远优先；本属性不代表资源清理已经成功完成。"""
        with self._lock:
            if self._failures or self._shutdown_reason == ShutdownReason.FAILURE:
                return EXIT_FAILURE
            if self._shutdown_reason == ShutdownReason.EVOLUTION:
                return EXIT_EVOLVED
            return EXIT_NORMAL

    def mark_running(self) -> None:
        with self._lock:
            if self._state != ApplicationState.STARTING:
                raise LifecycleFailure(f"Cannot start accepting work in state {self._state}")
            self._state = ApplicationState.RUNNING

    def require_running(self) -> None:
        with self._lock:
            if self._state in (ApplicationState.NEW, ApplicationState.STARTING):
                raise LifecycleFailure("Application has not finished initialization")
            if self._state != ApplicationState.RUNNING:
                raise ApplicationStoppingError("Application is no longer accepting work")

    @contextmanager
    def admission(self) -> Iterator[None]:
        """在锁内校验并登记输入；调用方不得在此执行 I/O 或 await。"""
        with self._lock:
            self.require_running()
            yield

    def next_input_sequence(self) -> int:
        """分配输入身份；接收方须在同一 admission 区间内登记完整记录。"""
        with self._lock:
            self._input_sequence += 1
            return self._input_sequence

    def _log_diagnostic(
        self, level: int, message: str, *args: object,
        error: BaseException | None = None,
    ) -> None:
        try:
            logger.log(level, message, *args,
                       exc_info=(type(error), error, error.__traceback__) if error is not None else None)
        except Exception:
            # 仅保护诊断出口；关闭状态与原始故障已提交，不能被handler故障覆盖。
            try:
                sys.stderr.write("Evolve Agent lifecycle diagnostic logging failed.\n")
            except Exception:
                pass

    def _request_shutdown_locked(self, reason: ShutdownReason) -> bool:
        if self._state in (ApplicationState.CLOSED, ApplicationState.FAILED):
            return False
        changed = self._shutdown_reason is None or (
            reason is ShutdownReason.FAILURE and self._shutdown_reason is not ShutdownReason.FAILURE
        )
        if self._shutdown_reason is None or reason is ShutdownReason.FAILURE:
            self._shutdown_reason = reason
        self._state = ApplicationState.STOPPING
        self.arm_shutdown_deadline()
        if self._loop is not None and self._shutdown_event is not None:
            self._loop.call_soon_threadsafe(self._shutdown_event.set)
        return changed

    def request_shutdown(self, reason: ShutdownReason) -> None:
        with self._lock:
            changed = self._request_shutdown_locked(reason)
        if changed:
            self._log_diagnostic(
                logging.ERROR if reason is ShutdownReason.FAILURE else logging.INFO,
                "Application shutdown requested | reason=%s thread=%s",
                reason.value, threading.current_thread().name,
            )

    def record_failure(self, error: BaseException) -> None:
        """Report the first original exception immediately, before shutdown finishes."""
        with self._lock:
            if any(existing is error for existing in self._reported_failure_objects):
                return
            self._reported_failure_objects.append(error)
            timeouts, remaining = split_cleanup_timeouts(error)
            changed = False
            if remaining is not None:
                self._failures.append(remaining)
                changed = self._request_shutdown_locked(ShutdownReason.FAILURE)
        if remaining is not None:
            self._log_diagnostic(
                logging.CRITICAL, "Application failure reported | thread=%s",
                threading.current_thread().name, error=remaining,
            )
        if changed:
            self._log_diagnostic(logging.ERROR, "Application shutdown requested | reason=failure")
        if timeouts:
            self._log_diagnostic(
                logging.WARNING, "External resource cleanup still pending | count=%d", len(timeouts),
            )

    def arm_shutdown_deadline(self) -> None:
        with self._lock:
            if self._shutdown_deadline is not None:
                return
            if self._state != ApplicationState.STOPPING:
                raise LifecycleFailure("Shutdown deadline can only start while stopping")
            timer = threading.Timer(
                APPLICATION_SHUTDOWN_TIMEOUT_SECONDS,
                os._exit,
                args=(EXIT_FAILURE,),
            )
            timer.daemon = True
            self._shutdown_deadline = timer
            timer.start()

    def disarm_shutdown_deadline(self) -> None:
        """仅由 asyncio.run 外层在事件循环及线程池结束后调用。"""
        with self._lock:
            timer = self._shutdown_deadline
            self._shutdown_deadline = None
            if timer is not None:
                timer.cancel()

    async def virtual_shotdown(self) -> None:
        with self._lock:
            self._state = (
                ApplicationState.FAILED
                if self._failures or self._shutdown_reason == ShutdownReason.FAILURE
                else ApplicationState.CLOSED
            )
        # 硬截止保留到 asyncio.run 外层，不能在框架解绑时提前取消。
