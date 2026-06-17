"""子进程 I/O 编码工具。

统一处理跨平台子进程输出，避免 Windows 本地编码、UTF-8 工具链和
Python 子进程默认编码之间互相冲突。
"""

from __future__ import annotations

import locale
import os
import subprocess
import sys
from typing import Any, Iterable, Mapping, Sequence


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