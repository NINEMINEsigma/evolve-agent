"""Package installation tool — always uses the same Python as the agent.

Uses sys.executable -m pip to guarantee the package is installed into
the same environment that's running the agent process.

Approval is handled by the unified AgentLoop tool execution entry.

Module-import-time registration via ``registry.register()``.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import Any, Dict, List

from abstract.tools.registry import registry, tool_error, tool_result
from entity.puretype import ToolDangerLevel
from entity.constant import SUBPROCESS_TIMEOUT_DEFAULT

logger = logging.getLogger(__name__)


# ── 工具 handler ─────────────────────────────────────────────────────


async def _handle_install_package(args: dict[str, Any]) -> dict:
    """Install one or more Python packages via pip."""
    packages: str = str(args.get("packages", "")).strip()
    upgrade: bool = args.get("upgrade", False)

    if not packages:
        return tool_error("packages is required — package names to install, space-separated")

    pkg_list: list[str] = [p.strip() for p in packages.split() if p.strip()]
    if not pkg_list:
        return tool_error("packages cannot be empty")

    # 审批由 AgentLoop 统一入口处理（handler 内不再重复确认）
    cmd = [sys.executable, "-m", "pip", "install"] + pkg_list
    if upgrade:
        cmd.append("--upgrade")

    logger.info("install_package | %s", " ".join(cmd))

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_DEFAULT)
    except subprocess.TimeoutExpired:
        return tool_error(f"pip install timed out ({SUBPROCESS_TIMEOUT_DEFAULT}s): {packages}")
    except Exception as exc:
        return tool_error(f"pip install failed: {exc}")

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
            message=f"Installation successful: {' '.join(installed or pkg_list)}\n{proc.stdout or ''}",
        )
    # Failure
    error_lines = [l for l in (proc.stderr or "").splitlines() if "ERROR:" in l]
    err_msg = error_lines[0] if error_lines else (proc.stderr or "Unknown error").strip()
    return tool_error(f"Installation failed: {err_msg}")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

registry.register(
    name="install_package",
    toolset="python",
    schema={
        # 安装 Python 包到当前运行环境中。
        #
        # ## 前置条件
        # 必须明确需要安装的包名，并能在 PyPI 或已配置索引中找到。
        # 必须提供 reason 说明安装原因，用于审批提示。
        # 此工具使用 sys.executable -m pip install，确保包安装到与 agent 相同的 Python 环境。
        #
        # ## 调用效果
        # 执行 pip install 安装指定包。可设置 upgrade=true 升级到最新版。
        # 返回安装的包名、退出码和标准输出摘要。
        #
        # ## 返回
        # ```json
        # {"packages": ["matplotlib"], "exit_code": 0, "message": "Installation successful: matplotlib\n..."}
        # ```
        #
        # ## 何时使用
        # - 运行代码需要某个未安装的第三方库时。
        # - 需要升级已安装库到最新版本时。
        #
        # ## 副作用/注意
        # - 修改当前 Python 环境，可能影响后续代码执行。
        # - 错误安装可能破坏环境；请只安装可信来源的包。
        # - 每次调用需要用户审批。
        # - 不要用 run_command 安装 pip 包。
        "description": """Install Python packages into the current runtime environment.

## Prerequisites
The package names to install must be clear and available on PyPI or the configured index. A reason explaining why the package is needed must be provided for the approval prompt. This tool always uses sys.executable -m pip install to ensure packages are installed into the same Python interpreter as the agent process.

## Effect
Runs pip install to install the specified packages. Set upgrade=true to upgrade to the latest version. Returns the installed package names, exit code, and a summary of stdout.

## Returns
```json
{"packages": ["matplotlib"], "exit_code": 0, "message": "Installation successful: matplotlib\n..."}
```

## When to Use
- When running code requires a third-party library that is not installed.
- When upgrading an installed library to the latest version.

## Side Effects / Notes
- Modifies the current Python environment and may affect subsequent code execution.
- Installing from untrusted sources can break the environment; only install trusted packages.
- Each invocation requires user approval.
- Do NOT use run_command to install pip packages.""",
        "parameters": {
            "type": "object",
            "properties": {
                "packages": {
                    "type": "string",
                    # 要安装的包名，多个包用空格分隔，如 "matplotlib pandas"。
                    "description": """Package names to install, space-separated, e.g. "matplotlib pandas".""",
                },
                "upgrade": {
                    "type": "boolean",
                    # 是否升级到最新版（pip install --upgrade），默认 false。
                    "description": """Whether to upgrade to the latest version (pip install --upgrade), default false.""",
                },
                "reason": {
                    "type": "string",
                    # 需要安装这些包的原因，将展示给用户以供审批。
                    "description": """Reason for installing these packages, shown to the user for approval.""",
                },
            },
            "required": ["packages", "reason"],
        },
    },
    handler=_handle_install_package,
    is_async=True,
    emoji="f4e6",
    danger_level=ToolDangerLevel.dangerous,
)