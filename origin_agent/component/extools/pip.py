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
        return tool_error("packages 是必填的 — 要安装的包名，空格分隔")

    pkg_list: List[str] = [p.strip() for p in packages.split() if p.strip()]
    if not pkg_list:
        return tool_error("packages 不能为空")

    # ── 用户确认 ──
    if session_id:
        result: ApprovalResult = await request_user_confirm(
            session_id, "install_package",
            {"packages": packages, "reason": reason},
            reason,
            f"安装包: `{packages}`\n原因: {reason}",
        )
    else:
        result = ApprovalResult(action="deny", deny_reason="缺少 session_id")

    if result.action == "deny":
        source_label = {"model": "审批模型", "user": "用户", "system": "系统"}.get(result.denied_by, "系统")
        return tool_error(
            f"[{source_label}拒绝] {result.deny_reason or '未知原因'}",
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
            "用户将被提示批准（允许一次）或拒绝安装。\n"
            "请始终包含 'reason' 解释需要安装的包的原因。\n\n"
            "示例:\n"
            "  install_package(packages=\"matplotlib\", reason=\"用于数据可视化\")\n"
            "  install_package(packages=\"pandas numpy\", upgrade=True, reason=\"数据科学库\")\n"
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
                "reason": {
                    "type": "string",
                    "description": "需要安装这些包的原因，将展示给用户以供审批。",
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