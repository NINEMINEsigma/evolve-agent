"""Windows ConPTY Shell会话的进程级生命周期管理。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import sys
import threading
import time
import uuid
from typing import Any

from entity.constant import (
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
)
from entity.puretype import ShellInfo, ShellOutputSlice
from system.sandbox import Sandbox, SandboxError
from system.shell_text import ShellTextNormalizer
from system.subprocess_utils import _kill_proc_tree

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
        event_loop: asyncio.AbstractEventLoop,
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
        termination: str | None = None,
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
            )

    def output_slice(
        self,
        offset: int,
        limit: int,
        wait_reason: str,
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


class ShellManager:
    """Application 持有的唯一 Shell会话管理器。"""

    _conpty_spawn_lock: threading.Lock = threading.Lock()

    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox
        self._shells: dict[str, _ShellSession] = {}
        self._session_aliases: dict[str, str] = {}
        self._registry_lock = threading.RLock()

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

    async def start_shell(
        self,
        owner_session_id: str,
        character_name: str,
        shell_type: str,
        cwd: str,
        command: str,
    ) -> tuple[ShellInfo, ShellOutputSlice, dict[str, str]]:
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
            resolved = self._sandbox.resolve_read(cwd)
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
        state.reader_thread = threading.Thread(
            target=self._reader_loop,
            args=(state,),
            daemon=True,
            name=f"shell-reader-{shell_id}",
        )
        state.reader_thread.start()

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

    async def read_shell(
        self,
        owner_session_id: str,
        character_name: str,
        shell_id: str,
        offset: int,
        limit: int,
        wait_timeout: float,
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

    async def write_shell(
        self,
        owner_session_id: str,
        character_name: str,
        shell_id: str,
        text: str,
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

    async def interrupt_shell(
        self,
        owner_session_id: str,
        character_name: str,
        shell_id: str,
    ) -> ShellOutputSlice:
        state = self._get_owned(owner_session_id, character_name, shell_id)
        async with state.operation_lock:
            self._require_running(state)
            start_offset = self._total_chars(state)
            try:
                await asyncio.to_thread(self._send_interrupt_blocking, state)
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

    async def stop_shell(
        self,
        owner_session_id: str,
        character_name: str,
        shell_id: str,
    ) -> ShellInfo:
        state = self._get_owned(owner_session_id, character_name, shell_id)
        await self._remove_and_stop(state)
        return state.info()

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

    async def stop_shell_for_user(
        self,
        session_id: str,
        shell_id: str,
    ) -> ShellInfo:
        with self._registry_lock:
            state = self._shells.get(shell_id)
            if state is None or state.session_id != session_id:
                raise ShellAccessError("Shell not found")
        await self._remove_and_stop(state)
        return state.info()

    def migrate_session(self, old_session_id: str, new_session_id: str) -> int:
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
                await self._remove_and_stop(state)
                stopped += 1
            except Exception:
                logger.exception(
                    "Failed to stop Shell during session cleanup | shell=%s session=%s",
                    state.shell_id,
                    session_id,
                )
        return stopped

    async def shutdown(self) -> int:
        with self._registry_lock:
            states = list(self._shells.values())
            self._session_aliases.clear()
        stopped = 0
        for state in states:
            try:
                await self._remove_and_stop(state)
                stopped += 1
            except Exception:
                logger.exception(
                    "Failed to stop Shell during application shutdown | shell=%s",
                    state.shell_id,
                )
        return stopped

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
        wait_for_quiet: bool,
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

    async def _write_line(self, state: _ShellSession, text: str) -> None:
        self._require_running(state)
        try:
            await asyncio.to_thread(self._write_line_blocking, state, text)
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

    async def _remove_and_stop(self, state: _ShellSession) -> None:
        state.closing.set()
        state.signal_output()
        async with state.operation_lock:
            with self._registry_lock:
                self._shells.pop(state.shell_id, None)
            await asyncio.to_thread(self._stop_state_blocking, state)

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

        # First terminate the child process so a blocked reader can leave read().
        if state.pid is not None:
            try:
                _kill_proc_tree(state.pid)
            except Exception:
                logger.warning(
                    "Failed to terminate Shell process tree | shell=%s pid=%s",
                    state.shell_id,
                    state.pid,
                    exc_info=True,
                )

        if state.reader_thread is None:
            state.reader_exited.set()
        reader_stopped = state.reader_exited.wait(SHELL_STOP_WAIT_SECONDS)
        if not reader_stopped:
            logger.warning(
                "Shell reader did not exit before PTY close | shell=%s pid=%s",
                state.shell_id,
                state.pid,
            )

        acquired = state.native_lock.acquire(timeout=SHELL_STOP_WAIT_SECONDS)
        if acquired:
            try:
                if not state.native_closed.is_set():
                    try:
                        exit_code = state.pty.exitstatus
                    except Exception:
                        exit_code = None
                    with state.lock:
                        if exit_code is not None or state.exit_code is None:
                            state.exit_code = exit_code
                    try:
                        state.pty.close(force=True)
                    except Exception:
                        logger.warning(
                            "PtyProcess.close(force=True) failed | shell=%s",
                            state.shell_id,
                            exc_info=True,
                        )
                    finally:
                        state.native_closed.set()
            finally:
                state.native_lock.release()
        else:
            # The reader never owns native_lock while blocked in read(). If a
            # foreign PTY call nevertheless holds it, do not deadlock cleanup.
            logger.error(
                "Timed out waiting for Shell native control lock; using emergency close | shell=%s",
                state.shell_id,
            )
            if not state.native_closed.is_set():
                try:
                    state.pty.close(force=True)
                except Exception:
                    logger.warning(
                        "Emergency PtyProcess.close(force=True) failed | shell=%s",
                        state.shell_id,
                        exc_info=True,
                    )
                finally:
                    state.native_closed.set()

        if state.reader_thread is not None and state.reader_thread.is_alive():
            state.reader_thread.join(timeout=SHELL_STOP_WAIT_SECONDS)
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
        shell_id: str,
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
        for namespace, path in sorted(self._sandbox.namespace_bases().items()):
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
    def _validate_line(text: str, *, allow_empty: bool, field: str) -> None:
        if not isinstance(text, str):
            raise ShellError(f"{field} must be a string")
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
