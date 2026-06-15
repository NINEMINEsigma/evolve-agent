"""后台服务管理工具 — 启动和停止长时间运行的后台进程。

属于 extools，模块导入时通过 ``registry.register()`` 注册两个工具：

  - ``start_background_service`` — 启动后台进程，返回 task_id + 日志路径
  - ``stop_background_service`` — 通过 task_id 停止后台进程

与 ``run_command`` 不同，此工具不等待进程完成，而是立即返回。
启动的进程以 daemon 方式运行，stdout/stderr 重定向到日志文件。
"""

from __future__ import annotations

import asyncio
import json
import locale
import logging
import subprocess  # nosec
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

from abstract.tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)

# ── 后台任务注册表 ───────────────────────────────────────────
# task_id -> {proc, log_path, command, start_time, pid, session_id}

_background_tasks: dict[str, dict[str, Any]] = {}

# ── sandbox 引用 ──────────────────────────────────────────────
from system.sandbox import _kill_proc_tree


def _resolve_logical_path(logical: str) -> str | None:
    """将逻辑路径（如 ws:logs/...）解析为真实文件系统路径。"""
    from component.tools.filesystem import _s as _get_sandbox
    try:
        from system.sandbox import Access
        r = _get_sandbox().resolve(logical, Access.WRITE)
        return str(r.real)
    except Exception:
        return None


# ── 启动工具 handler ─────────────────────────────────────────


async def _handle_start_background_service(args: dict[str, Any]) -> dict:
    """启动后台服务进程，立即返回 task_id 和日志路径。

    参数与 run_command 类似，但进程在后台运行不等待完成。
    """
    raw_cmd: Any = args.get("command")
    cwd: str = str(args.get("cwd", "ws:")).strip()
    session_id: str = str(args.get("_session_id", ""))

    # ── 验证命令 ──
    if not raw_cmd or not isinstance(raw_cmd, list):
        return tool_error("'command' must be a non-empty list of strings")
    cmd_parts: list[str] = [str(p) for p in raw_cmd]
    if not cmd_parts:
        return tool_error("'command' must be a non-empty list")

    # 审批由 AgentLoop 统一入口处理（handler 内不再重复确认）
    # ── 解析 cwd ──
    from component.tools.filesystem import _s as _get_sandbox
    from system.sandbox import Access, SandboxError
    try:
        r = _get_sandbox().resolve(cwd, Access.READ)
        cwd_real: str = str(r.real)
    except SandboxError as exc:
        return tool_error(f"cwd resolution failed: {exc}", cwd=cwd)

    # ── 生成 task_id 和日志路径 ──
    task_id: str = uuid.uuid4().hex[:12]
    log_dir = f"ws:logs/background"
    log_path = f"{log_dir}/{task_id}.log"

    log_dir_real: str | None = _resolve_logical_path(log_dir)
    if not log_dir_real:
        return tool_error(f"Unable to resolve log directory: {log_dir}")

    # 确保日志目录存在
    Path(log_dir_real).mkdir(parents=True, exist_ok=True)

    log_file_real = str(Path(log_dir_real) / f"{task_id}.log")

    # ── 解析命令参数中的沙箱路径 ──
    # 将 ws:/fork:/fix: 前缀的逻辑路径展开为真实绝对路径。
    from component.tools.filesystem import _s as _get_sandbox
    resolved_parts: list[str] = []
    for part in cmd_parts:
        if any(part.startswith(p) for p in ("ws:", "fork:", "fix:")):
            try:
                r = _get_sandbox().resolve_read(part)
                resolved_parts.append(str(r.real))
            except SandboxError:
                resolved_parts.append(part)
        else:
            resolved_parts.append(part)

    # ── 启动后台进程 ──
    try:
        # ... (keep existing popen code)
        popen_kwargs: dict = {
            "cwd": cwd_real,
            "stdout": open(log_file_real, "w", encoding=locale.getpreferredencoding(), errors="replace"),
            "stderr": subprocess.STDOUT,
            "text": False,
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        proc: subprocess.Popen = subprocess.Popen(resolved_parts, **popen_kwargs)
        popen_kwargs["stdout"].close()

        _background_tasks[task_id] = {
            "proc": proc,
            "pid": proc.pid,
            "log_path": log_path,
            "log_file_real": log_file_real,
            "command": cmd_parts,
            "start_time": time.time(),
            "session_id": session_id,
        }

        logger.info(
            "Background service started | task=%s pid=%d cmd=%s",
            task_id, proc.pid, " ".join(cmd_parts),
        )

        return tool_result(
            success=True,
            task_id=task_id,
            log_path=log_path,
            pid=proc.pid,
            command=cmd_parts,
            message=f"Background service started (task_id={task_id}, pid={proc.pid})",
        )

    except Exception as exc:
        logger.exception("Failed to start background service: %s", exc)
        return tool_error(f"Failed to start background service: {exc}")


# ── 停止工具 handler ─────────────────────────────────────────


async def _handle_stop_background_service(args: dict[str, Any]) -> dict:
    """通过 task_id 停止后台服务进程。"""
    task_id: str = str(args.get("task_id", "")).strip()

    if not task_id:
        return tool_error("'task_id' is required")

    task: dict[str, Any] | None = _background_tasks.pop(task_id, None)

    if task is None and task_id.isdigit():
        # 直接用 PID 尝试
        pid = int(task_id)
        try:
            _kill_proc_tree(pid)
        except Exception:
            pass
        return tool_result(
            stopped=True,
            task_id=task_id,
            pid=pid,
            message=f"已发送终止信号 (PID={pid})",
        )

    if task is None:
        return tool_result(
            stopped=False,
            task_id=task_id,
            message=f"未找到 task_id={task_id} 对应的后台任务",
        )

    pid: int = task["pid"]
    log_path: str = task["log_path"]

    try:
        _kill_proc_tree(pid)
        # 等待进程退出
        proc = task["proc"]
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("Process %d did not exit within 5s after kill", pid)

        logger.info("Background service stopped | task=%s pid=%d", task_id, pid)

        return tool_result(
            stopped=True,
            task_id=task_id,
            pid=pid,
            log_path=log_path,
            message=f"Background service stopped (task_id={task_id}, pid={pid})",
        )

    except Exception as exc:
        logger.exception("Failed to stop background service %s: %s", task_id, exc)
        return tool_error(f"Failed to stop background service: {exc}", task_id=task_id)


# ── 进程清理（agent 关闭时调用）───────────────────────────


def cleanup_background_services() -> int:
    """Kill all tracked background service processes. Returns count killed.

    由 ``main.py`` 在 agent 关闭时调用，确保没有孤儿进程残留。
    """
    count = 0
    for task_id, task in list(_background_tasks.items()):
        pid: int = task["pid"]
        proc: subprocess.Popen = task["proc"]
        log_path: str = task["log_path"]
        try:
            _kill_proc_tree(pid)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning(
                    "Background service %s (pid=%d) did not exit within 5s after kill",
                    task_id, pid,
                )
            del _background_tasks[task_id]
            count += 1
            logger.info(
                "Background service cleaned up | task=%s pid=%d log=%s",
                task_id, pid, log_path,
            )
        except Exception as exc:
            logger.error(
                "Failed to clean up background service %s (pid=%d): %s",
                task_id, pid, exc,
            )
    return count


# ── 公开 API（供 gateway/server.py 调用）────────────────────

def list_background_tasks(session_id: str) -> list[dict[str, Any]]:
    """返回指定会话关联的所有后台任务。"""
    result: list[dict[str, Any]] = []
    for task_id, task in _background_tasks.items():
        if task.get("session_id") == session_id:
            proc: subprocess.Popen = task["proc"]
            status = "running" if proc.poll() is None else "stopped"
            result.append({
                "task_id": task_id,
                "pid": task["pid"],
                "command": task["command"],
                "start_time": task["start_time"],
                "log_path": task["log_path"],
                "status": status,
            })
    return result


def stop_background_task(task_id: str) -> dict[str, Any]:
    """通过 task_id 停止后台任务，返回操作结果。"""
    task: dict[str, Any] | None = _background_tasks.pop(task_id, None)

    if task is None and task_id.isdigit():
        pid = int(task_id)
        try:
            _kill_proc_tree(pid)
        except Exception:
            pass
        return {"stopped": True, "task_id": task_id, "pid": pid, "message": f"已发送终止信号 (PID={pid})"}

    if task is None:
        return {"stopped": False, "task_id": task_id, "message": f"未找到 task_id={task_id} 对应的后台任务"}

    pid: int = task["pid"]
    try:
        _kill_proc_tree(pid)
        proc = task["proc"]
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("Process %d did not exit within 5s after kill", pid)
        return {"stopped": True, "task_id": task_id, "pid": pid, "message": f"已停止 (task_id={task_id}, pid={pid})"}
    except Exception as exc:
        logger.exception("Failed to stop background service %s: %s", task_id, exc)
        return {"stopped": False, "task_id": task_id, "message": str(exc)}


# ── 注册 ─────────────────────────────────────────────────────

registry.register(
    name="start_background_service",
    toolset="background",
    schema={
        # 在后台启动一个长时间运行的服务进程，立即返回而不等待进程完成。
        # 适用于启动 Web 服务器、API 服务、监控进程等。
        # 与 run_command 不同：
        #   - 进程在后台运行，不阻塞 agent
        #   - stdout/stderr 合并写入日志文件
        #   - 返回 task_id，可用 stop_background_service 停止
        "description": (
            "Start a long-running service process in the background and return "
            "immediately without waiting for the process to complete.\n"
            "Useful for starting web servers, API services, monitoring processes, etc.\n\n"
            "Unlike run_command:\n"
            "  - The process runs in the background, does not block the agent\n"
            "  - stdout/stderr are merged and written to a log file\n"
            "  - Returns a task_id that can be used with stop_background_service\n\n"
            "Returns:\n"
            "  - success: whether the service started successfully\n"
            "  - task_id: task identifier (for stopping the service)\n"
            "  - log_path: log file path (ws: namespace)\n"
            "  - pid: process ID\n"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "array",
                    "items": {"type": "string"},
                    # 命令及参数列表，例如 ['python', '-m', 'http.server', '8080']。
                    "description": "Command and argument list, e.g. ['python', '-m', 'http.server', '8080'].",
                },
                "reason": {
                    "type": "string",
                    # 启动此后台服务的原因。
                    "description": "Reason for starting this background service.",
                },
                "cwd": {
                    "type": "string",
                    # 工作目录（ws: 命名空间，默认 'ws:'）。
                    "description": "Working directory (ws: namespace, default 'ws:').",
                    "default": "ws:",
                },
            },
            "required": ["command", "reason"],
        },
    },
    handler=_handle_start_background_service,
    is_async=True,
    emoji="🔄",
    danger_level="dangerous",
)

registry.register(
    name="stop_background_service",
    toolset="background",
    schema={
        # 停止一个由 start_background_service 启动的后台服务进程。
        # 通过 start_background_service 返回的 task_id 找到对应进程并强制终止。
        # 也可以直接传入 PID（纯数字字符串）尝试终止。
        "description": (
            "Stop a background service process started by start_background_service.\n"
            "Find the process by task_id and force-terminate it.\n\n"
            "You can also pass a PID (numeric string) directly to attempt termination.\n\n"
            "Returns:\n"
            "  - stopped: whether the service was successfully stopped\n"
            "  - task_id: requested task ID\n"
            "  - pid: process ID\n"
            "  - log_path: log file path (if found in registry)\n"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    # start_background_service 返回的 task_id，或直接传入 PID 数字。
                    "description": "task_id returned by start_background_service, or a PID number directly.",
                },
            },
            "required": ["task_id"],
        },
    },
    handler=_handle_stop_background_service,
    is_async=True,
    emoji="⏹",
)