"""SSH 远程操作工具集 — 通过系统原生 ssh/scp 命令连接远程服务器。

工具清单
========
ssh_exec      在远程服务器上执行 shell 命令
ssh_upload    使用 scp 上传本地文件到远程
ssh_download  使用 scp 从远程下载文件到本地

所有工具共享以下安全 flag：
  - StrictHostKeyChecking=accept-new  首次连接自动接受，密钥变更时拒绝
  - BatchMode=yes                     禁止交互式密码提示，避免挂死
  - ConnectTimeout=10                 连接阶段超时 10 秒

模块导入时通过 ``registry.register()`` 注册。
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from typing import Any, Dict

from abstract.tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 公共参数
# ---------------------------------------------------------------------------

_SSH_COMMON_FLAGS: list[str] = [
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=10",
]

# ---------------------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------------------


def _validate_target(target: str) -> str | None:
    """校验 target 格式为 user@host，返回 None 表示通过，否则返回错误信息。"""
    t = target.strip()
    if not t:
        return "target is required and must be in user@host format"
    if "@" not in t:
        return f"target must be in user@host format, got: {t!r}"
    parts = t.split("@")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return f"target must be in user@host format, got: {t!r}"
    return None


from component.approval import ApprovalResult, request_user_confirm


# ---------------------------------------------------------------------------
# ssh_exec
# ---------------------------------------------------------------------------


async def _handle_ssh_exec(args: Dict[str, Any]) -> str:
    """在远程服务器上执行 shell 命令（需用户审批）。"""
    target: str = str(args.get("target", "")).strip()
    command: str = str(args.get("command", "")).strip()
    port: int = int(args.get("port", 22))
    timeout: int = int(args.get("timeout", 30))
    reason: str = str(args.get("reason", "")).strip()
    session_id: str = str(args.get("_session_id", ""))

    # --- 校验 ---
    err = _validate_target(target)
    if err:
        return tool_error(err)
    if not command:
        return tool_error("command is required")
    if not reason:
        return tool_error("reason is required — please explain why this remote command needs to be executed")

    # --- 用户确认 ---
    if session_id:
        approval_result: ApprovalResult = await request_user_confirm(
            session_id, "ssh_exec",
            {"target": target, "command": command[:200], "reason": reason},
            reason,
            f"SSH operation: execute on {target}: {command[:200]}\nReason: {reason}",
        )
    else:
        approval_result = ApprovalResult(action="deny", deny_reason="missing session_id")

    if approval_result.action == "deny":
        # 审批模型/用户/系统
        source_label = {"model": "approval model", "user": "user", "system": "system"}.get(approval_result.denied_by, "system")
        return tool_error(
            f"[{source_label} denied] {approval_result.deny_reason or 'unknown reason'}",
            target=target,
            command=command[:200],
            denied=True,
        )

    # --- 构造命令 ---
    cmd: list[str] = [
        "ssh",
        "-p", str(port),
        *_SSH_COMMON_FLAGS,
        target,
        command,
    ]

    logger.info("ssh_exec: %s@%s:%d — %s", target.split("@")[0], target.split("@")[1], port, command[:120])

    # --- 执行 ---
    try:
        result: subprocess.CompletedProcess[str] = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return tool_error(
            f"SSH command timed out after {timeout}s",
            target=target,
            command=command[:200],
        )
    except FileNotFoundError:
        return tool_error(
            "ssh command not found. Is OpenSSH client installed?",
            target=target,
        )

    return tool_result(
        success=(result.returncode == 0),
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.returncode,
        target=target,
    )


# ---------------------------------------------------------------------------
# ssh_upload
# ---------------------------------------------------------------------------


async def _handle_ssh_upload(args: Dict[str, Any]) -> str:
    """使用 scp 上传本地文件到远程服务器（需用户审批）。"""
    target: str = str(args.get("target", "")).strip()
    local_path: str = str(args.get("local_path", "")).strip()
    remote_path: str = str(args.get("remote_path", "")).strip()
    port: int = int(args.get("port", 22))
    recursive: bool = bool(args.get("recursive", False))
    reason: str = str(args.get("reason", "")).strip()
    session_id: str = str(args.get("_session_id", ""))

    # --- 校验 ---
    err = _validate_target(target)
    if err:
        return tool_error(err)
    if not local_path:
        return tool_error("local_path is required")
    if not remote_path:
        return tool_error("remote_path is required")
    if not reason:
        return tool_error("reason is required — please explain why the file needs to be uploaded")

    # --- 用户确认 ---
    if session_id:
        approval_result: ApprovalResult = await request_user_confirm(
            session_id, "ssh_upload",
            {"local_path": local_path, "remote_path": remote_path, "target": target, "reason": reason},
            reason,
            f"SSH operation: upload {local_path} → {target}:{remote_path}\nReason: {reason}",
        )
    else:
        approval_result = ApprovalResult(action="deny", deny_reason="missing session_id")

    if approval_result.action == "deny":
        # 审批模型/用户/系统
        source_label = {"model": "approval model", "user": "user", "system": "system"}.get(approval_result.denied_by, "system")
        return tool_error(
            f"[{source_label} denied] {approval_result.deny_reason or 'unknown reason'}",
            target=target,
            local_path=local_path,
            remote_path=remote_path,
            denied=True,
        )

    # --- 构造命令 ---
    cmd: list[str] = ["scp", "-P", str(port), *_SSH_COMMON_FLAGS]
    if recursive:
        cmd.append("-r")
    cmd.extend([local_path, f"{target}:{remote_path}"])

    logger.info("ssh_upload: %s → %s:%s", local_path, target, remote_path)

    # --- 执行 ---
    try:
        result: subprocess.CompletedProcess[str] = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return tool_error(
            "SCP upload timed out after 120s",
            target=target,
            local_path=local_path,
            remote_path=remote_path,
        )
    except FileNotFoundError:
        return tool_error(
            "scp command not found. Is OpenSSH client installed?",
            target=target,
        )

    return tool_result(
        success=(result.returncode == 0),
        local_path=local_path,
        remote_path=remote_path,
        target=target,
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.returncode,
    )


# ---------------------------------------------------------------------------
# ssh_download
# ---------------------------------------------------------------------------


async def _handle_ssh_download(args: Dict[str, Any]) -> str:
    """使用 scp 从远程服务器下载文件到本地（需用户审批）。"""
    target: str = str(args.get("target", "")).strip()
    remote_path: str = str(args.get("remote_path", "")).strip()
    local_path: str = str(args.get("local_path", "")).strip()
    port: int = int(args.get("port", 22))
    recursive: bool = bool(args.get("recursive", False))
    reason: str = str(args.get("reason", "")).strip()
    session_id: str = str(args.get("_session_id", ""))

    # --- 校验 ---
    err = _validate_target(target)
    if err:
        return tool_error(err)
    if not remote_path:
        return tool_error("remote_path is required")
    if not local_path:
        return tool_error("local_path is required")
    if not reason:
        return tool_error("reason is required — please explain why the file needs to be downloaded")

    # --- 用户确认 ---
    if session_id:
        approval_result: ApprovalResult = await request_user_confirm(
            session_id, "ssh_download",
            {"remote_path": remote_path, "target": target, "local_path": local_path, "reason": reason},
            reason,
            f"SSH operation: download {target}:{remote_path} → {local_path}\nReason: {reason}",
        )
    else:
        approval_result = ApprovalResult(action="deny", deny_reason="missing session_id")

    if approval_result.action == "deny":
        # 审批模型/用户/系统
        source_label = {"model": "approval model", "user": "user", "system": "system"}.get(approval_result.denied_by, "system")
        return tool_error(
            f"[{source_label} denied] {approval_result.deny_reason or 'unknown reason'}",
            target=target,
            remote_path=remote_path,
            local_path=local_path,
            denied=True,
        )

    # --- 构造命令 ---
    cmd: list[str] = ["scp", "-P", str(port), *_SSH_COMMON_FLAGS]
    if recursive:
        cmd.append("-r")
    cmd.extend([f"{target}:{remote_path}", local_path])

    logger.info("ssh_download: %s:%s → %s", target, remote_path, local_path)

    # --- 执行 ---
    try:
        result: subprocess.CompletedProcess[str] = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return tool_error(
            "SCP download timed out after 120s",
            target=target,
            remote_path=remote_path,
            local_path=local_path,
        )
    except FileNotFoundError:
        return tool_error(
            "scp command not found. Is OpenSSH client installed?",
            target=target,
        )

    return tool_result(
        success=(result.returncode == 0),
        remote_path=remote_path,
        local_path=local_path,
        target=target,
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.returncode,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_COMMON_PARAMS_TARGET_PORT: dict = {
    "target": {
        "type": "string",
        # 远程目标，格式 user@host（如 root@10.0.0.1）。
        "description": "Remote target in user@host format (e.g. root@10.0.0.1).",
    },
    "port": {
        "type": "integer",
        # SSH 端口（默认 22）。
        "description": "SSH port (default 22).",
        "default": 22,
    },
}

registry.register(
    name="ssh_exec",
    toolset="extools",
    schema={
        # 在远程服务器上执行 shell 命令并返回 stdout、stderr 和退出码。
        # 使用系统原生 ssh 命令，依赖已有的 SSH 配置（~/.ssh/config、密钥等）。
        # 首次连接到新主机时自动接受 host key，密钥变更时拒绝连接。
        # 用户将被提示批准（允许一次）或拒绝该操作。
        # 始终包含 'reason' 解释需要执行远程命令的原因。
        "description": (
            "Execute a shell command on a remote server and return stdout, stderr, and exit code. "
            "Uses system-native ssh, relying on existing SSH configuration "
            "(~/.ssh/config, keys, etc.). "
            "Automatically accepts host key on first connection, rejects on key mismatch. "
            "The user will be prompted to approve (allow once) or deny the operation. "
            "Always include 'reason' explaining why the remote command is needed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                **_COMMON_PARAMS_TARGET_PORT,
                "command": {
                    "type": "string",
                    # 要在远程服务器上执行的 shell 命令。
                    "description": "Shell command to execute on the remote server.",
                },
                "timeout": {
                    "type": "integer",
                    # 命令执行超时秒数（默认 30）。
                    "description": "Command execution timeout in seconds (default 30).",
                    "default": 30,
                },
                "reason": {
                    "type": "string",
                    # 需要执行此远程命令的原因，将展示给用户以供审批。
                    "description": "Reason for executing this remote command, shown to user for approval.",
                },
            },
            "required": ["target", "command", "reason"],
        },
    },
    handler=_handle_ssh_exec,
    is_async=True,
    emoji="🖥",
    danger_level="dangerous",
)

registry.register(
    name="ssh_upload",
    toolset="extools",
    schema={
        # 使用 scp 将本地文件上传到远程服务器。
        # 支持递归上传目录（设置 recursive=true）。
        # 用户将被提示批准（允许一次）或拒绝该操作。
        # 始终包含 'reason' 解释需要上传文件的原因。
        "description": (
            "Upload local files to a remote server using scp. "
            "Supports recursive directory upload (set recursive=true). "
            "The user will be prompted to approve (allow once) or deny the operation. "
            "Always include 'reason' explaining why the file upload is needed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                **_COMMON_PARAMS_TARGET_PORT,
                "local_path": {
                    "type": "string",
                    # 本地文件或目录的路径。
                    "description": "Path to the local file or directory.",
                },
                "remote_path": {
                    "type": "string",
                    # 远程目标路径。
                    "description": "Remote destination path.",
                },
                "recursive": {
                    "type": "boolean",
                    # 是否递归上传目录（默认 false）。
                    "description": "Whether to recursively upload a directory (default false).",
                    "default": False,
                },
                "reason": {
                    "type": "string",
                    # 需要上传文件的原因，将展示给用户以供审批。
                    "description": "Reason for uploading the file, shown to user for approval.",
                },
            },
            "required": ["target", "local_path", "remote_path", "reason"],
        },
    },
    handler=_handle_ssh_upload,
    is_async=True,
    emoji="📤",
    danger_level="dangerous",
)

registry.register(
    name="ssh_download",
    toolset="extools",
    schema={
        # 使用 scp 从远程服务器下载文件到本地。
        # 支持递归下载目录（设置 recursive=true）。
        # 用户将被提示批准（允许一次）或拒绝该操作。
        # 始终包含 'reason' 解释需要下载文件的原因。
        "description": (
            "Download files from a remote server to local using scp. "
            "Supports recursive directory download (set recursive=true). "
            "The user will be prompted to approve (allow once) or deny the operation. "
            "Always include 'reason' explaining why the file download is needed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                **_COMMON_PARAMS_TARGET_PORT,
                "remote_path": {
                    "type": "string",
                    # 远程文件或目录的路径。
                    "description": "Path to the remote file or directory.",
                },
                "local_path": {
                    "type": "string",
                    # 本地目标路径。
                    "description": "Local destination path.",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "是否递归下载目录（默认 false）。",
                    "default": False,
                },
                "reason": {
                    "type": "string",
                    "description": "需要下载文件的原因，将展示给用户以供审批。",
                },
            },
            "required": ["target", "remote_path", "local_path", "reason"],
        },
    },
    handler=_handle_ssh_download,
    is_async=True,
    emoji="📥",
    danger_level="dangerous",
)