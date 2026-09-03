"""跨平台原子文件写入工具。

在 Windows 上使用 MoveFileExW + MOVEFILE_REPLACE_EXISTING 执行原子替换，
避免 os.replace 在目标文件被占用或处于瞬态锁定时报 [WinError 5]。
在其他平台回退到 os.replace。
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Union

logger = logging.getLogger(__name__)

_PathT = Union[str, Path]

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.MoveFileExW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
    ]
    _kernel32.MoveFileExW.restype = wintypes.BOOL

    _MOVEFILE_REPLACE_EXISTING = 0x00000001
    _MOVEFILE_WRITE_THROUGH = 0x00000008

    def _win_move_file_replace(src: str, dst: str) -> None:
        """使用 Windows MoveFileExW 原子替换目标文件。"""
        if not _kernel32.MoveFileExW(
            src,
            dst,
            _MOVEFILE_REPLACE_EXISTING | _MOVEFILE_WRITE_THROUGH,
        ):
            err = ctypes.get_last_error()
            raise ctypes.WinError(err)


def replace_atomic(src: _PathT, dst: _PathT) -> None:
    """原子替换 dst 为 src。

    Windows: 使用 MoveFileExW + MOVEFILE_REPLACE_EXISTING，并针对瞬态锁定
    做短时间的指数退避重试。
    其他平台: 使用 os.replace。
    """
    src_path = Path(src)
    dst_path = Path(dst)
    if sys.platform != "win32":
        os.replace(src_path, dst_path)
        return

    src_str = str(src_path.resolve())
    dst_str = str(dst_path.resolve())
    last_err: OSError | None = None
    for attempt in range(5):
        try:
            _win_move_file_replace(src_str, dst_str)
            return
        except OSError as exc:
            last_err = exc
            if attempt == 4:
                break
            delay = 0.005 * (2 ** attempt)
            logger.warning(
                "Atomic replace failed for %s -> %s on attempt %d: %s. "
                "Retrying in %.0f ms.",
                src_str, dst_str, attempt + 1, exc, delay * 1000,
            )
            time.sleep(delay)
    raise last_err  # type: ignore[misc]


def write_text_atomic(
    path: _PathT,
    content: str,
    *,
    tmp_suffix: str = ".tmp",
    encoding: str = "utf-8",
) -> None:
    """原子写入文本内容到 path。

    先写入同目录下的临时文件，再原子替换到目标文件。
    临时文件与目标文件同目录，确保替换在同一卷内完成。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}{tmp_suffix}")
    tmp.write_text(content, encoding=encoding)
    replace_atomic(tmp, target)


def create_text_exclusive(
    path: _PathT,
    content: str,
    *,
    encoding: str = "utf-8",
) -> None:
    """独占创建文本文件；目标已存在时绝不覆盖。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding=encoding) as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _file_identity(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def move_file_no_replace(src: _PathT, dst: _PathT) -> None:
    """移动文件且永不替换既有目标。

    先独占创建空 reservation，再核验它仍是本次创建的文件，最后才用源文件
    原子替换 reservation。失败时保留源文件。
    """
    source = Path(src)
    target = Path(dst)
    if not source.is_file():
        raise FileNotFoundError(f"Source file not found: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as reservation:
        reservation.flush()
        os.fsync(reservation.fileno())
    identity = _file_identity(target)
    try:
        if _file_identity(target) != identity or target.stat().st_size != 0:
            raise FileExistsError(f"Destination reservation changed: {target}")
        replace_atomic(source, target)
    except BaseException:
        try:
            if target.exists() and _file_identity(target) == identity:
                target.unlink()
        except OSError:
            logger.warning("Failed to clean destination reservation: %s", target, exc_info=True)
        raise


def copy_tree_no_replace(src: _PathT, dst: _PathT) -> None:
    """递归复制目录且要求目标不存在；失败时回滚本次目标。"""
    source = Path(src)
    target = Path(dst)
    if not source.is_dir():
        raise FileNotFoundError(f"Source directory not found: {source}")
    if target.exists():
        raise FileExistsError(f"Destination already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(source, target, symlinks=True)
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise


def move_tree_no_replace(src: _PathT, dst: _PathT) -> None:
    """无覆盖复制完整目录后删除源；复制失败时源保持不变。"""
    source = Path(src)
    target = Path(dst)
    copy_tree_no_replace(source, target)
    try:
        shutil.rmtree(source)
    except BaseException:
        logger.error(
            "Directory copied but source cleanup failed: %s -> %s",
            source,
            target,
            exc_info=True,
        )
        raise
