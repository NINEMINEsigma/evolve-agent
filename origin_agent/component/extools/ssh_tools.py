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

import logging
import subprocess
from typing import Any, Dict

from abstract.tools.registry import registry, tool_error, tool_result
from entity.constant import LOG_PREVIEW_CHARS, SUBPROCESS_TIMEOUT_DEFAULT

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


# ---------------------------------------------------------------------------
# ssh_exec
# ---------------------------------------------------------------------------


async def _handle_ssh_exec(args: dict[str, Any]) -> dict:
    """在远程服务器上执行 shell 命令。"""
    target: str = str(args.get("target", "")).strip()
    command: str = str(args.get("command", "")).strip()
    port: int = int(args.get("port", 22))
    timeout: int = int(args.get("timeout", SUBPROCESS_TIMEOUT_DEFAULT))
    reason: str = str(args.get("reason", "")).strip()

    # --- 校验 ---
    err = _validate_target(target)
    if err:
        return tool_error(err)
    if not command:
        return tool_error("command is required")
    if not reason:
        return tool_error("reason is required — please explain why this remote command needs to be executed")

    # 审批由 AgentLoop 统一入口处理（handler 内不再重复确认）
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
            command=command[:LOG_PREVIEW_CHARS],
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


async def _handle_ssh_upload(args: dict[str, Any]) -> dict:
    """使用 scp 上传本地文件到远程服务器。"""
    target: str = str(args.get("target", "")).strip()
    local_path: str = str(args.get("local_path", "")).strip()
    remote_path: str = str(args.get("remote_path", "")).strip()
    port: int = int(args.get("port", 22))
    recursive: bool = bool(args.get("recursive", False))
    reason: str = str(args.get("reason", "")).strip()

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

    # 审批由 AgentLoop 统一入口处理（handler 内不再重复确认）
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
            timeout=SUBPROCESS_TIMEOUT_DEFAULT,
        )
    except subprocess.TimeoutExpired:
        return tool_error(
            "SCP upload timed out after {}s".format(SUBPROCESS_TIMEOUT_DEFAULT),
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


async def _handle_ssh_download(args: dict[str, Any]) -> dict:
    """使用 scp 从远程服务器下载文件到本地。"""
    target: str = str(args.get("target", "")).strip()
    remote_path: str = str(args.get("remote_path", "")).strip()
    local_path: str = str(args.get("local_path", "")).strip()
    port: int = int(args.get("port", 22))
    recursive: bool = bool(args.get("recursive", False))
    reason: str = str(args.get("reason", "")).strip()

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

    # 审批由 AgentLoop 统一入口处理（handler 内不再重复确认）
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
            timeout=SUBPROCESS_TIMEOUT_DEFAULT,
        )
    except subprocess.TimeoutExpired:
        return tool_error(
            "SCP download timed out after {}s".format(SUBPROCESS_TIMEOUT_DEFAULT),
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
        #
        # ## 前置条件
        # 必须能够通过系统原生 ssh 命令以无交互方式连接到 target，依赖已有的 SSH 配置（~/.ssh/config、密钥等）。
        # 首次连接新主机时自动接受 host key；密钥变更时拒绝连接。
        # 必须提供 reason 说明执行该远程命令的原因，用于审批提示。
        #
        # ## 调用效果
        # 通过 ssh 在 target 上执行 command，返回命令输出与退出码。
        # 连接阶段 10 秒超时，命令执行超时由 timeout 参数控制。
        #
        # ## 返回
        # ```json
        # {"success": true, "stdout": "...", "stderr": "...", "exit_code": 0, "target": "user@host"}
        # ```
        #
        # ## 何时使用
        # - 需要在远程服务器上执行管理命令。
        # - 检查远程服务状态、部署或收集日志。
        #
        # ## 副作用/注意
        # - 远程命令可能对服务器造成直接影响，danger_level 为 dangerous。
        # - 每次调用需要用户审批（允许一次/总是允许/拒绝）。
        # - 禁止交互式密码输入，若未配置密钥/SSH 配置会导致失败。
        "description": """Execute a shell command on a remote server and return stdout, stderr, and exit code.

## Prerequisites
Connection to the target must be possible via the system-native ssh command without interaction, relying on existing SSH configuration (~/.ssh/config, keys, etc.). The host key is automatically accepted on first connection and rejected if it changes later. A reason explaining why the remote command is needed must be provided for the approval prompt.

## Effect
Executes command on the target host via ssh and returns the output and exit code. Connection phase times out after 10 seconds; command execution timeout is controlled by the timeout parameter.

## Returns
```json
{"success": true, "stdout": "...", "stderr": "...", "exit_code": 0, "target": "user@host"}
```

## When to Use
- Run administrative commands on a remote server.
- Check remote service status, deploy software, or collect logs.

## Side Effects / Notes
- Remote commands can directly affect the server; danger_level is dangerous.
- Each invocation requires user approval (allow once / always allow / deny).
- Interactive password prompts are disabled; failure occurs if keys or SSH config are not set up.""",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    # 远程目标，格式 user@host（如 root@10.0.0.1）。
                    "description": """Remote target in user@host format (e.g. root@10.0.0.1).""",
                },
                "port": {
                    "type": "integer",
                    # SSH 端口（默认 22）。
                    "description": """SSH port (default 22).""",
                    "default": 22,
                },
                "command": {
                    "type": "string",
                    # 要在远程服务器上执行的 shell 命令。
                    "description": """Shell command to execute on the remote server.""",
                },
                "timeout": {
                    "type": "integer",
                    # 命令执行超时秒数（默认 SUBPROCESS_TIMEOUT_DEFAULT）。
                    "description": """Command execution timeout in seconds.""",
                    "default": SUBPROCESS_TIMEOUT_DEFAULT,
                },
                "reason": {
                    "type": "string",
                    # 需要执行此远程命令的原因，将展示给用户以供审批。
                    "description": """Reason for executing this remote command, shown to the user for approval.""",
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
        #
        # ## 前置条件
        # 必须能够通过系统原生 scp/ssh 以无交互方式连接到 target。
        # local_path 和 remote_path 必须明确提供。
        # 必须提供 reason 说明上传原因，用于审批提示。
        #
        # ## 调用效果
        # 通过 scp 将 local_path 上传到 target 的 remote_path。
        # 支持 recursive=true 递归上传目录。
        #
        # ## 返回
        # ```json
        # {"success": true, "local_path": "...", "remote_path": "...", "target": "user@host", "stdout": "...", "stderr": "...", "exit_code": 0}
        # ```
        #
        # ## 何时使用
        # - 将本地生成的文件、脚本或目录部署到远程服务器。
        # - 批量上传配置或资源。
        #
        # ## 副作用/注意
        # - 会覆盖远程目标路径的同名文件（scp 默认行为）。
        # - 每次调用需要用户审批。
        # - recursive=true 时上传整个目录结构。
        "description": """Upload local files to a remote server using scp.

## Prerequisites
Connection to the target must be possible via the system-native scp/ssh commands without interaction. local_path and remote_path must be explicitly provided. A reason explaining why the upload is needed must be provided for the approval prompt.

## Effect
Uploads local_path to remote_path on the target host via scp. Supports recursive directory upload when recursive=true.

## Returns
```json
{"success": true, "local_path": "...", "remote_path": "...", "target": "user@host", "stdout": "...", "stderr": "...", "exit_code": 0}
```

## When to Use
- Deploy locally generated files, scripts, or directories to a remote server.
- Upload configurations or resources in bulk.

## Side Effects / Notes
- Overwrites files with the same name at the remote destination (default scp behavior).
- Each invocation requires user approval.
- recursive=true uploads the entire directory structure.""",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    # 远程目标，格式 user@host（如 root@10.0.0.1）。
                    "description": """Remote target in user@host format (e.g. root@10.0.0.1).""",
                },
                "port": {
                    "type": "integer",
                    # SSH 端口（默认 22）。
                    "description": """SSH port (default 22).""",
                    "default": 22,
                },
                "local_path": {
                    "type": "string",
                    # 本地文件或目录的路径。
                    "description": """Path to the local file or directory.""",
                },
                "remote_path": {
                    "type": "string",
                    # 远程目标路径。
                    "description": """Remote destination path.""",
                },
                "recursive": {
                    "type": "boolean",
                    # 是否递归上传目录（默认 false）。
                    "description": """Whether to recursively upload a directory (default false).""",
                    "default": False,
                },
                "reason": {
                    "type": "string",
                    # 需要上传文件的原因，将展示给用户以供审批。
                    "description": """Reason for uploading the file, shown to the user for approval.""",
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
        #
        # ## 前置条件
        # 必须能够通过系统原生 scp/ssh 以无交互方式连接到 target。
        # remote_path 和 local_path 必须明确提供。
        # 必须提供 reason 说明下载原因，用于审批提示。
        #
        # ## 调用效果
        # 通过 scp 将 target 上 remote_path 的文件或目录下载到 local_path。
        # 支持 recursive=true 递归下载目录。
        #
        # ## 返回
        # ```json
        # {"success": true, "remote_path": "...", "local_path": "...", "target": "user@host", "stdout": "...", "stderr": "...", "exit_code": 0}
        # ```
        #
        # ## 何时使用
        # - 从远程服务器获取日志、配置文件或数据。
        # - 批量下载远程目录。
        #
        # ## 副作用/注意
        # - 会覆盖本地目标路径的同名文件（scp 默认行为）。
        # - 每次调用需要用户审批。
        # - recursive=true 时下载整个目录结构。
        "description": """Download files from a remote server to local using scp.

## Prerequisites
Connection to the target must be possible via the system-native scp/ssh commands without interaction. remote_path and local_path must be explicitly provided. A reason explaining why the download is needed must be provided for the approval prompt.

## Effect
Downloads the file or directory at remote_path from the target host to local_path via scp. Supports recursive directory download when recursive=true.

## Returns
```json
{"success": true, "remote_path": "...", "local_path": "...", "target": "user@host", "stdout": "...", "stderr": "...", "exit_code": 0}
```

## When to Use
- Retrieve logs, configuration files, or data from a remote server.
- Download entire remote directories.

## Side Effects / Notes
- Overwrites files with the same name at the local destination (default scp behavior).
- Each invocation requires user approval.
- recursive=true downloads the entire directory structure.""",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    # 远程目标，格式 user@host（如 root@10.0.0.1）。
                    "description": """Remote target in user@host format (e.g. root@10.0.0.1).""",
                },
                "port": {
                    "type": "integer",
                    # SSH 端口（默认 22）。
                    "description": """SSH port (default 22).""",
                    "default": 22,
                },
                "remote_path": {
                    "type": "string",
                    # 远程文件或目录的路径。
                    "description": """Path to the remote file or directory.""",
                },
                "local_path": {
                    "type": "string",
                    # 本地目标路径。
                    "description": """Local destination path.""",
                },
                "recursive": {
                    "type": "boolean",
                    # 是否递归下载目录（默认 false）。
                    "description": """Whether to recursively download a directory (default false).""",
                    "default": False,
                },
                "reason": {
                    "type": "string",
                    # 需要下载文件的原因，将展示给用户以供审批。
                    "description": """Reason for downloading the file, shown to the user for approval.""",
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