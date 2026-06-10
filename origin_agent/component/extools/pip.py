"""Package installation tool — always uses the same Python as the agent.

Uses sys.executable -m pip to guarantee the package is installed into
the same environment that's running the agent process.

Each installation requires user approval via CONFIRM_REQUEST/CONFIRM_RESPONSE
WebSocket handshake, matching the pattern used by run_command and run_python.

Module-import-time registration via ``registry.register()``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
from typing import Any, Dict, List

from abstract.tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)


from component.approval import ApprovalResult, request_user_confirm


# ── 工具 handler ─────────────────────────────────────────────────────


async def _handle_install_package(args: Dict[str, Any]) -> str:
    """Install one or more Python packages via pip, after user approval."""
    packages: str = str(args.get("packages", "")).strip()
    upgrade: bool = args.get("upgrade", False)
    reason: str = str(args.get("reason", "")).strip()
    session_id: str = str(args.get("_session_id", ""))

    if not packages:
        return tool_error("packages is required — package names to install, space-separated")

    pkg_list: List[str] = [p.strip() for p in packages.split() if p.strip()]
    if not pkg_list:
        return tool_error("packages cannot be empty")

    # ── 用户确认（若已由 _execute_tool 预审批则跳过）──
    _pre_approved: bool = args.get("_pre_approved", False)
    _approval_action: str = args.get("_approval_action", "allow_once")
    if _pre_approved:
        result = ApprovalResult(action=_approval_action)
    elif session_id:
        result: ApprovalResult = await request_user_confirm(
            session_id, "install_package",
            {"packages": packages, "reason": reason},
            reason,
            f"Install package: `{packages}`\nReason: {reason}",
        )
    else:
        result = ApprovalResult(action="deny", deny_reason="missing session_id")

    if result.action == "deny":
        # 审批模型/用户/系统
        source_label = {"model": "approval model", "user": "user", "system": "system"}.get(result.denied_by, "system")
        return tool_error(
            f"[{source_label} denied] {result.deny_reason or 'unknown reason'}",
            packages=pkg_list,
            denied=True,
        )

    # ── 执行安装 ──
    cmd = [sys.executable, "-m", "pip", "install"] + pkg_list
    if upgrade:
        cmd.append("--upgrade")

    logger.info("install_package | %s", " ".join(cmd))

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return tool_error(f"pip install timed out (120s): {packages}")
    except Exception as exc:
        return tool_error(f"pip install failed: {exc}")

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
        # 始终使用 ``sys.executable -m pip install`` 执行，保证包安装到
        # 与 agent 进程相同的 Python 解释器。不要用 ``run_command`` 安装 pip 包。
        # 用户将被提示批准（允许一次）或拒绝安装。
        # 请始终包含 'reason' 解释需要安装的包的原因。
        "description": (
            "Install Python packages into the current runtime environment.\n\n"
            "Always uses ``sys.executable -m pip install`` to ensure packages "
            "are installed to the same Python interpreter as the agent process. "
            "Do NOT use ``run_command`` to install pip packages.\n\n"
            "The user will be prompted to approve (allow once) or deny the installation.\n"
            "Always include 'reason' explaining why the package is needed.\n\n"
            "Examples:\n"
            "  install_package(packages=\"matplotlib\", reason=\"for data visualization\")\n"
            "  install_package(packages=\"pandas numpy\", upgrade=True, reason=\"data science libraries\")\n"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "packages": {
                    "type": "string",
                    # 要安装的包名，多个包用空格分隔，如 "matplotlib pandas"
                    "description": "Package names to install, space-separated, e.g. \"matplotlib pandas\"",
                },
                "upgrade": {
                    "type": "boolean",
                    # 是否升级到最新版（pip install --upgrade），默认 false
                    "description": "Whether to upgrade to the latest version (pip install --upgrade), default false",
                },
                "reason": {
                    "type": "string",
                    # 需要安装这些包的原因，将展示给用户以供审批。
                    "description": "Reason for installing these packages, shown to the user for approval.",
                },
            },
            "required": ["packages", "reason"],
        },
    },
    handler=_handle_install_package,
    is_async=True,
    emoji="\U0001f4e6",
    danger_level="dangerous",
)