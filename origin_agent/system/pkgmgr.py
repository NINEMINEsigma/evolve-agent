"""包管理器检测 — 优先 pnpm，回退 npm。

前端构建依赖 pnpm 或 npm，本模块在运行时检测可用的包管理器，
返回可直接传给 ``subprocess.run`` 的可执行文件名。
"""

from __future__ import annotations

import shutil
import sys


def detect_package_manager() -> str:
    """检测可用的包管理器，优先 pnpm，回退 npm。

    返回值可直接用于 ``subprocess.run`` 的 ``args[0]``。
    Windows 上 ``CreateProcess`` 不自动搜索 PATHEXT 扩展名，
    因此返回带 ``.cmd`` 后缀的显式文件名。

    :raises FileNotFoundError: pnpm 和 npm 均不在 PATH 中。
    """
    # (shutil.which 探测名, subprocess 使用的文件名)
    candidates: list[tuple[str, str]] = [
        ("pnpm", "pnpm.cmd" if sys.platform == "win32" else "pnpm"),
        ("npm", "npm.cmd" if sys.platform == "win32" else "npm"),
    ]
    for detect_name, bin_name in candidates:
        if shutil.which(detect_name):
            return bin_name
    raise FileNotFoundError("Neither pnpm nor npm found in PATH")