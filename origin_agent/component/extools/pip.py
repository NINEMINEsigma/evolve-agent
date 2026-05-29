"""Package installation tool — always uses the same Python as the agent.

Uses sys.executable -m pip to guarantee the package is installed into
the same environment that's running the agent process.

Module-import-time registration via ``registry.register()``.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import Any, Dict

from abstract.tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)


def _handle_install_package(args: Dict[str, Any]) -> str:
    """Install one or more Python packages via pip, using the agent's Python interpreter."""
    packages: str = str(args.get("packages", "")).strip()
    upgrade: bool = args.get("upgrade", False)

    if not packages:
        return tool_error("packages 是必填的 — 要安装的包名，空格分隔")

    pkg_list = [p.strip() for p in packages.split() if p.strip()]
    if not pkg_list:
        return tool_error("packages 不能为空")

    cmd = [sys.executable, "-m", "pip", "install"] + pkg_list
    if upgrade:
        cmd.append("--upgrade")

    logger.info("install_package | %s", " ".join(cmd))

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return tool_error(f"pip install 超时 (120s): {packages}")
    except Exception as exc:
        return tool_error(f"pip install 失败: {exc}")

    std = (proc.stdout or "") + "\n" + (proc.stderr or "")
    success = proc.returncode == 0

    if success:
        # Extract installed package names from output
        installed = []
        for line in (proc.stdout or "").splitlines():
            if "Successfully installed" in line:
                installed = line.replace("Successfully installed", "").strip().split()
                break
        return tool_result(
            packages=installed or pkg_list,
            exit_code=0,
            message=f"安装成功: {' '.join(installed or pkg_list)}\n{proc.stdout or ''}",
        )
    # Failure
    error_lines = [l for l in (proc.stderr or "").splitlines() if "ERROR:" in l]
    err_msg = error_lines[0] if error_lines else (proc.stderr or "Unknown error").strip()
    return tool_error(f"安装失败: {err_msg}")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

registry.register(
    name="install_package",
    toolset="python",
    schema={
        "description": (
            "安装 Python 包到当前运行环境中。\n\n"
            "始终使用 ``sys.executable -m pip install`` 执行，保证包安装到\n"
            "与 agent 进程相同的 Python 解释器。不要用 ``run_command`` 安装 pip 包。\n\n"
            "示例:\n"
            "  install_package(packages=\"matplotlib\")\n"
            "  install_package(packages=\"pandas numpy\", upgrade=True)\n"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "packages": {
                    "type": "string",
                    "description": "要安装的包名，多个包用空格分隔，如 \"matplotlib pandas\"",
                },
                "upgrade": {
                    "type": "boolean",
                    "description": "是否升级到最新版（pip install --upgrade），默认 false",
                },
            },
            "required": ["packages"],
        },
    },
    handler=_handle_install_package,
    emoji="\U0001f4e6",
)