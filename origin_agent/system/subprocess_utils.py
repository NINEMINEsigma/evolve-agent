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
from typing import Any, Mapping, Sequence

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
    stderr: bytes | str | None,
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
    **kwargs: Any,
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


class SubprocessRunner:
    """子进程执行的唯一实现层，持有活动进程登记表与进程树终止逻辑。

    由 ``Application`` 持有全局单例，并在 ``init()`` 中注入 ``Sandbox``。
    提供同步 ``run()``（任意线程可用）与真异步 ``run_async()``（事件循环内 await）。
    活动进程按 ``session_id`` 分桶登记，供中断路径 ``kill_active()`` 按会话终止。
    """

    def __init__(self) -> None:
        # session_id -> [Popen | asyncio.subprocess.Process]；kill_active 终止用。
        self._active_procs: dict[str, list[subprocess.Popen | asyncio.subprocess.Process]] = {}
        self._procs_lock: threading.Lock = threading.Lock()

    # -- 同步入口（任意线程） ----------------------------------------------- #

    def run(
        self,
        args: list[str],
        *,
        cwd: str,
        timeout: float | None = None,
        extra_env: dict[str, str] | None = None,
        session_id: str = "",
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

        # 使用 Popen 以支持超时时强制终止整个进程树。
        # subprocess.run(timeout=...) 在 Windows 上不能可靠地
        # 终止子进程（例如 pnpm 生成的 node 进程）。
        popen_kwargs: dict = {
            "cwd": cwd,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": False,
            "env": env,
        }
        if sys.platform == "win32":
            # CREATE_NEW_PROCESS_GROUP 允许发送 CTRL_BREAK_EVENT，
            # 但我们将使用 taskkill 进行更可靠的进程树终止。
            popen_kwargs["creationflags"] = windows_process_group_flags()
        proc: subprocess.Popen = subprocess.Popen(args, **popen_kwargs)  # nosec
        with self._procs_lock:
            self._active_procs.setdefault(session_id, []).append(proc)
        stdout: bytes
        stderr: bytes
        try:
            if timeout is not None:
                stdout, stderr = proc.communicate(timeout=timeout)
            else:
                stdout, stderr = proc.communicate()
        except subprocess.TimeoutExpired:
            _kill_proc_tree(proc.pid)
            stdout, stderr = b"", b""
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            raise subprocess.TimeoutExpired(
                cmd=args[0], timeout=timeout if timeout is not None else 0, output="", stderr="",
            )
        finally:
            # 移除登记。kill_active 可能已清空整个 key（列表为空或 key 已删），须判空。
            with self._procs_lock:
                proc_list = self._active_procs.get(session_id)
                if proc_list and proc in proc_list:
                    proc_list.remove(proc)
                    if not proc_list:
                        self._active_procs.pop(session_id, None)

        return completed_process_from_bytes(
            args=args,
            returncode=proc.returncode,
            stdout=stdout,
            stderr=stderr,
        )

    # -- 真异步入口（事件循环内 await） ------------------------------------- #

    async def run_async(
        self,
        args: list[str],
        *,
        cwd: str,
        timeout: float | None = None,
        extra_env: dict[str, str] | None = None,
        session_id: str = "",
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
        proc: asyncio.subprocess.Process = await asyncio.create_subprocess_exec(
            *args, **popen_kwargs,
        )  # nosec
        with self._procs_lock:
            self._active_procs.setdefault(session_id, []).append(proc)
        stdout: bytes
        stderr: bytes
        try:
            if timeout is not None:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
            else:
                stdout, stderr = await proc.communicate()
        except asyncio.TimeoutError:
            _kill_proc_tree(proc.pid)
            try:
                await asyncio.wait_for(proc.wait(), 5)
            except asyncio.TimeoutError:
                pass
            raise subprocess.TimeoutExpired(
                cmd=args[0], timeout=timeout if timeout is not None else 0, output="", stderr="",
            )
        except asyncio.CancelledError:
            _kill_proc_tree(proc.pid)
            try:
                await asyncio.wait_for(proc.wait(), 5)
            except (asyncio.TimeoutError, Exception):
                pass
            raise
        finally:
            # 移除登记。kill_active 可能已清空整个 key（列表为空或 key 已删），须判空。
            with self._procs_lock:
                proc_list = self._active_procs.get(session_id)
                if proc_list and proc in proc_list:
                    proc_list.remove(proc)
                    if not proc_list:
                        self._active_procs.pop(session_id, None)

        return completed_process_from_bytes(
            args=args,
            returncode=proc.returncode,
            stdout=stdout,
            stderr=stderr,
        )

    # -- 中断终止 ---------------------------------------------------------- #

    def kill_active(self, session_id: str) -> None:
        """终止指定 session 登记的所有活动子进程树；session_id 为空串时终止全部。

        在事件循环线程调用（ToolExecutor / SubAgentLoop 中断路径）。
        duck-type 兼容 ``subprocess.Popen``（同步 ``run()`` 产出）与
        ``asyncio.subprocess.Process``（``run_async()`` 产出）：
        - Popen：``poll() is None`` 判活 → 杀树 + ``wait(timeout=1)`` 收割。
        - asyncio Process：``returncode is None`` 判活 → 仅杀树（收割由
          ``run_async`` 的 ``CancelledError`` 分支 ``await proc.wait()`` 负责）。
        幂等：仅终止仍存活的进程。
        """
        with self._procs_lock:
            if session_id:
                procs = self._active_procs.pop(session_id, [])
            else:
                procs = [p for v in self._active_procs.values() for p in v]
                self._active_procs.clear()
        for proc in procs:
            # duck-type 判活：Popen.poll() vs asyncio Process.returncode
            if isinstance(proc, subprocess.Popen):
                # subprocess.Popen（同步 run() 产出）
                if proc.poll() is None:
                    _kill_proc_tree(proc.pid)
                    try:
                        proc.wait(timeout=1)
                    except Exception:
                        pass
            else:
                # asyncio.subprocess.Process（run_async() 产出）
                if proc.returncode is None:
                    _kill_proc_tree(proc.pid)
                    # 不 await wait —— kill_active 为同步方法；
                    # 收割由 run_async 取消分支的 await proc.wait() 负责。