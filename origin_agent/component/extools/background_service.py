"""后台服务管理工具 — 启动和停止长时间运行的后台进程。

属于 extools，模块导入时通过 ``registry.register()`` 注册三个工具：

  - ``start_background_service``  — 启动后台进程，返回 task_id + 日志路径
  - ``stop_background_service``   — 通过 task_id 停止后台进程
  - ``start_watching_service``    — 启动后台进程并监视输出，按自适应间隔
    将增量输出 POST 到指定动态端点

与 ``run_command`` 不同，这些工具不等待进程完成，而是立即返回。
启动的进程以 daemon 方式运行，stdout/stderr 重定向到日志文件
（watching 类型由 reader 线程读取后双写到缓冲区和日志文件）。
"""

from __future__ import annotations

import asyncio
import json
import locale
import logging
import subprocess  # nosec
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

import httpx

from abstract.tools.registry import registry, tool_error, tool_result
from entity.puretype import ToolAvailability, ToolDangerLevel
from entity.constant import (
    NAMESPACE_PREFIXES,
    SUBPROCESS_SOFT_CLEANUP_WAIT_TIME,
    WATCHING_MIN_INTERVAL,
    WATCHING_DEFAULT_LONG_INTERVAL,
    WATCHING_DEFAULT_SHORT_INTERVAL,
)

logger = logging.getLogger(__name__)

# ── 后台任务注册表 ───────────────────────────────────────────
# task_id -> {proc, log_path, command, start_time, pid, session_id, [watch]}

_background_tasks: dict[str, dict[str, Any]] = {}

# ── sandbox 引用 ──────────────────────────────────────────────
from system.sandbox import _kill_proc_tree
from system.subprocess_utils import windows_process_group_flags


def _resolve_logical_path(logical: str) -> str | None:
    """将逻辑路径（如 ws:logs/...）解析为真实文件系统路径。"""
    from component.tools.filesystem import _s as _get_sandbox
    try:
        from system.sandbox import Access
        r = _get_sandbox().resolve(logical, Access.WRITE)
        return str(r.real)
    except Exception:
        logger.warning("Failed to resolve background service path '%s'", logical, exc_info=True)
        return None


# ── watching 任务运行时状态 ─────────────────────────────────


class _WatchState:
    """单个 watching 任务的运行时状态。

    不继承 BaseModel — 含 threading.Event 等非序列化字段，
    属于运行时工具类。
    """

    def __init__(
        self,
        callback_url: str,
        markers: list[str],
        long_interval: int,
        short_interval: int,
        log_file: Any,
    ) -> None:
        self.buffer: str = ""                    # 待发送的增量输出
        self.marker_hit: bool = False            # 当前周期是否命中标识符
        self.stop_event: threading.Event = threading.Event()
        self.flusher_thread: threading.Thread | None = None
        self.reader_thread: threading.Thread | None = None
        self.log_file: Any = log_file            # 已打开的日志文件句柄
        self.callback_url: str = callback_url   # 完整 POST URL
        self.markers: list[str] = markers
        self.long_interval: int = long_interval
        self.short_interval: int = short_interval


# ── watching 线程辅助函数 ───────────────────────────────────


def _post_to_endpoint(url: str, message: str) -> None:
    """POST message 到动态端点，失败时仅 logger.warning 不重试。"""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(url, json={"message": message})
            if resp.status_code != 200:
                logger.warning(
                    "POST to endpoint failed: %s status=%d", url, resp.status_code,
                )
    except Exception as exc:
        logger.warning("POST to endpoint failed: %s error=%s", url, exc)


def _reader_loop(task_id: str) -> None:
    """持续读取子进程 stdout/stderr，双写到缓冲区和日志文件。

    进程退出后触发最终 flush（附带退出码 POST 到动态端点）。
    """
    task = _background_tasks.get(task_id)
    if not task or "watch" not in task:
        return
    proc: subprocess.Popen = task["proc"]
    watch: _WatchState = task["watch"]
    log_file = watch.log_file

    while not watch.stop_event.is_set():
        try:
            # proc.stdout is BufferedReader when text=False; read1 reads available bytes
            chunk = proc.stdout.read1(4096)  # type: ignore[union-attr]
        except Exception:
            break
        if not chunk:
            if proc.poll() is not None:
                break
            time.sleep(0.1)
            continue
        text = chunk.decode(errors="replace")
        watch.buffer += text
        try:
            log_file.write(text)
            log_file.flush()
        except Exception:
            logger.warning("Failed to write log for watching task %s", task_id, exc_info=True)

    # 进程退出后触发最终 flush
    exit_code = proc.returncode if proc.returncode is not None else -1
    _final_flush(task_id, exit_code)


def _flusher_loop(task_id: str) -> None:
    """周期性检查缓冲区，按自适应间隔 POST 增量输出到动态端点。

    每轮根据上一轮缓冲区内容是否命中标识符决定等待时长：
      - 命中 → 等待 short_interval
      - 未命中 → 等待 long_interval
    缓冲区为空时静默跳过不发送。
    """
    task = _background_tasks.get(task_id)
    if not task or "watch" not in task:
        return
    watch: _WatchState = task["watch"]

    while not watch.stop_event.is_set():
        interval = watch.short_interval if watch.marker_hit else watch.long_interval
        if watch.stop_event.wait(interval):
            break  # 被停止信号唤醒

        if not watch.buffer:
            continue

        content = watch.buffer
        watch.buffer = ""
        watch.marker_hit = any(m in content for m in watch.markers)
        _post_to_endpoint(watch.callback_url, content)


def _final_flush(task_id: str, exit_code: int) -> None:
    """进程退出后发送最终批次输出 + 退出码通知到动态端点。

    由 reader 线程在检测到进程退出后调用。
    """
    task = _background_tasks.get(task_id)
    if not task or "watch" not in task:
        return
    watch: _WatchState = task["watch"]

    content = watch.buffer
    watch.buffer = ""

    message = f"[watching-service] task_id={task_id} exited (code={exit_code})\n{content}"
    _post_to_endpoint(watch.callback_url, message)

    watch.stop_event.set()


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
        if any(part.startswith(p) for p in NAMESPACE_PREFIXES):
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
            popen_kwargs["creationflags"] = windows_process_group_flags()

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
            logger.warning("Failed to kill background process PID=%d", pid, exc_info=True)
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

    # watching 类型：停止 flusher 线程，kill 后返回缓冲区剩余内容
    watch: _WatchState | None = task.get("watch")

    try:
        if watch is not None:
            watch.stop_event.set()

        _kill_proc_tree(pid)
        # 等待进程退出
        proc = task["proc"]
        try:
            proc.wait(timeout=SUBPROCESS_SOFT_CLEANUP_WAIT_TIME)
        except subprocess.TimeoutExpired:
            logger.warning("Process %d did not exit within 5s after kill", pid)

        # watching 类型：关闭日志文件句柄，取出缓冲区剩余内容
        remaining_buffer: str = ""
        if watch is not None:
            try:
                watch.log_file.close()
            except Exception:
                logger.warning("Failed to close log file for task %s", task_id, exc_info=True)
            remaining_buffer = watch.buffer
            watch.buffer = ""

        logger.info(
            "Background service stopped | task=%s pid=%d watching=%s",
            task_id, pid, watch is not None,
        )

        result = tool_result(
            stopped=True,
            task_id=task_id,
            pid=pid,
            log_path=log_path,
            message=f"Background service stopped (task_id={task_id}, pid={pid})",
        )
        if watch is not None:
            result["remaining_buffer"] = remaining_buffer
        return result

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
        watch: _WatchState | None = task.get("watch")
        try:
            # watching 类型：先停 flusher 线程，不做最终 flush（会话已结束）
            if watch is not None:
                watch.stop_event.set()
            _kill_proc_tree(pid)
            try:
                proc.wait(timeout=SUBPROCESS_SOFT_CLEANUP_WAIT_TIME)
            except subprocess.TimeoutExpired:
                logger.warning(
                    "Background service %s (pid=%d) did not exit within 5s after kill",
                    task_id, pid,
                )
            # watching 类型：关闭日志文件句柄
            if watch is not None:
                try:
                    watch.log_file.close()
                except Exception:
                    logger.warning("Failed to close log file for task %s", task_id, exc_info=True)
            del _background_tasks[task_id]
            count += 1
            logger.info(
                "Background service cleaned up | task=%s pid=%d log=%s watching=%s",
                task_id, pid, log_path, watch is not None,
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
            watch: _WatchState | None = task.get("watch")
            entry: dict[str, Any] = {
                "task_id": task_id,
                "pid": task["pid"],
                "command": task["command"],
                "start_time": task["start_time"],
                "log_path": task["log_path"],
                "status": status,
                "type": "watching" if watch is not None else "background",
            }
            if watch is not None:
                entry["marker_hit"] = watch.marker_hit
            result.append(entry)
    return result


def stop_background_task(task_id: str) -> dict[str, Any]:
    """通过 task_id 停止后台任务，返回操作结果。"""
    task: dict[str, Any] | None = _background_tasks.pop(task_id, None)

    if task is None and task_id.isdigit():
        pid = int(task_id)
        try:
            _kill_proc_tree(pid)
        except Exception:
            logger.warning("Failed to kill background process PID=%d", pid, exc_info=True)
        return {"stopped": True, "task_id": task_id, "pid": pid, "message": f"已发送终止信号 (PID={pid})"}

    if task is None:
        return {"stopped": False, "task_id": task_id, "message": f"未找到 task_id={task_id} 对应的后台任务"}

    pid: int = task["pid"]
    log_path: str = task["log_path"]
    watch: _WatchState | None = task.get("watch")
    try:
        if watch is not None:
            watch.stop_event.set()
        _kill_proc_tree(pid)
        proc = task["proc"]
        try:
            proc.wait(timeout=SUBPROCESS_SOFT_CLEANUP_WAIT_TIME)
        except subprocess.TimeoutExpired:
            logger.warning("Process %d did not exit within 5s after kill", pid)
        result: dict[str, Any] = {
            "stopped": True,
            "task_id": task_id,
            "pid": pid,
            "log_path": log_path,
            "message": f"已停止 (task_id={task_id}, pid={pid})",
        }
        if watch is not None:
            try:
                watch.log_file.close()
            except Exception:
                logger.warning("Failed to close log file for task %s", task_id, exc_info=True)
            result["remaining_buffer"] = watch.buffer
            watch.buffer = ""
        return result
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
        # 与 run_command 不同：进程在后台运行不阻塞 agent，stdout/stderr 合并写入日志文件，
        # 返回 task_id 供 stop_background_service 使用。
        # 如需监视输出并回调动态端点，请使用 start_watching_service 代替。
        #
        # ## 前置条件
        # - command 必须是非空字符串列表。
        # - cwd 所在命名空间必须可读。
        # - 日志目录 ws:logs/background/ 必须可写。
        #
        # ## 调用效果
        # 解析命令中的沙箱逻辑路径后，在后台启动子进程。
        # stdout/stderr 合并重定向到 ws:logs/background/{task_id}.log。
        # 立即返回 task_id、pid 和日志路径。
        #
        # ## 返回
        # ```json
        # {"success": true, "task_id": "abc123", "log_path": "ws:logs/background/abc123.log", "pid": 1234, "command": ["python", "-m", "http.server", "8080"]}
        # ```
        #
        # ## 何时使用
        # - 启动 Web 服务器、API 服务、后台监控进程。
        # - 运行需要持续监听的服务（如 dev server、proxy）。
        #
        # ## 副作用/注意
        # - ⚠️ 进程在后台运行，agent 不会自动等待其完成。
        # - 如需获取实时输出，需定期使用 read_file 读取 log_path。
        # - agent 关闭时会调用 cleanup_background_services 强制清理所有残留进程。
        # - 错误调用可对系统造成毁灭性打击。
        "description": """Start a long-running service process in the background and return immediately without waiting for completion. Useful for web servers, API services, monitoring processes, etc.

## Prerequisites
- command must be a non-empty list of strings.
- The cwd namespace must be readable.
- The log directory ws:logs/background/ must be writable.

## Effect
Resolves sandbox logical paths in the command, then launches the subprocess in the background. stdout/stderr are merged and redirected to ws:logs/background/{task_id}.log. Returns task_id, pid, and log_path immediately.

## Returns
```json
{"success": true, "task_id": "abc123", "log_path": "ws:logs/background/abc123.log", "pid": 1234, "command": ["python", "-m", "http.server", "8080"]}
```

## When to Use
- Start a web server, API service, or background monitoring process.
- Run a service that needs to keep listening (e.g. dev server, proxy).

## Side Effects / Notes
- ⚠️ The process runs in the background; the agent does not wait for it.
- To check real-time output, periodically read the log_path with read_file.
- On agent shutdown, cleanup_background_services force-terminates all remaining background processes.
- Misuse can cause catastrophic damage.""",
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
    danger_level=ToolDangerLevel.dangerous,
    availability=ToolAvailability.MAIN | ToolAvailability.MULTI_AGENT,
)

registry.register(
    name="stop_background_service",
    toolset="background",
    schema={
        # 停止一个由 start_background_service 或 start_watching_service 启动的后台服务进程。
        # 通过 task_id 找到对应进程并强制终止。
        # 也可以直接传入 PID（纯数字字符串）尝试终止。
        #
        # ## 前置条件
        # - task_id 必须是由 start_background_service 或 start_watching_service 返回的有效 ID，
        #   或一个存在的 PID。
        #
        # ## 调用效果
        # 通过 task_id 查找进程，发送终止信号并等待最多 5 秒让其退出，超时则强制杀死整个进程树。
        # 找不到 task_id 但输入为纯数字时，直接当作 PID 终止。
        # 对于 watching 类型任务：停止 flusher 线程，关闭日志文件句柄，
        # 缓冲区剩余内容通过返回值 remaining_buffer 字段返回（不 POST 到动态端点）。
        #
        # ## 返回
        # ```json
        # {"stopped": true, "task_id": "abc123", "pid": 1234, "log_path": "ws:logs/background/abc123.log", "message": "..."}
        # ```
        # watching 类型额外返回 remaining_buffer 字段：
        # ```json
        # {"stopped": true, "task_id": "abc123", "pid": 1234, "log_path": "...", "remaining_buffer": "...", "message": "..."}
        # ```
        #
        # ## 何时使用
        # - 停止之前通过 start_background_service 启动的后台服务。
        # - 停止之前通过 start_watching_service 启动的监视服务。
        # - 直接终止某个已知 PID 的进程。
        #
        # ## 副作用/注意
        # - 强制终止进程树，可能导致数据丢失或文件损坏。
        # - 等待进程退出最多 5 秒，超时则强制杀死。
        # - 无法找到 task_id 且非纯数字时返回 stopped=false。
        # - watching 类型的缓冲区剩余内容通过返回值返回，不发送到动态端点。
        "description": """Stop a background service process started by start_background_service or start_watching_service. Finds the process by task_id and force-terminates it. You can also pass a PID (numeric string) directly.

## Prerequisites
- task_id must be a valid ID returned by start_background_service or start_watching_service, or an existing PID.

## Effect
Looks up the process by task_id, sends a termination signal, and waits up to 5 seconds for exit before force-killing the entire process tree. If the task_id is not found but the input is numeric, it is treated as a PID and terminated directly. For watching-type tasks: stops the flusher thread, closes the log file handle, and returns the remaining buffer content via the remaining_buffer field (does NOT POST to the dynamic endpoint).

## Returns
```json
{"stopped": true, "task_id": "abc123", "pid": 1234, "log_path": "ws:logs/background/abc123.log", "message": "Background service stopped (task_id=abc123, pid=1234)"}
```
For watching-type tasks, an additional remaining_buffer field is included:
```json
{"stopped": true, "task_id": "abc123", "pid": 1234, "log_path": "...", "remaining_buffer": "...", "message": "..."}
```

## When to Use
- Stop a background service previously started by start_background_service.
- Stop a watching service previously started by start_watching_service.
- Terminate a process with a known PID.

## Side Effects / Notes
- Force-terminates the process tree; may cause data loss or file corruption.
- Waits up to 5 seconds for graceful exit, then force-kills.
- Returns stopped=false when the task_id cannot be found and is not numeric.
- For watching-type tasks, the remaining buffer is returned in the tool result, not POSTed to the dynamic endpoint.""",
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
    availability=ToolAvailability.MAIN | ToolAvailability.MULTI_AGENT,
)


# ── watching 服务 handler + 注册 ────────────────────────────


async def _handle_start_watching_service(args: dict[str, Any]) -> dict:
    """启动后台进程并监视输出，按自适应间隔 POST 增量输出到动态端点。"""
    raw_cmd: Any = args.get("command")
    endpoint_name: str = str(args.get("endpoint_name", "")).strip()
    raw_markers: Any = args.get("markers", [])
    long_interval: int = int(args.get("long_interval", WATCHING_DEFAULT_LONG_INTERVAL))
    short_interval: int = int(args.get("short_interval", WATCHING_DEFAULT_SHORT_INTERVAL))
    cwd: str = str(args.get("cwd", "ws:")).strip()
    session_id: str = str(args.get("_session_id", ""))

    # ── 参数校验 ──
    if not raw_cmd or not isinstance(raw_cmd, list):
        return tool_error("'command' must be a non-empty list of strings")
    cmd_parts: list[str] = [str(p) for p in raw_cmd]
    if not cmd_parts:
        return tool_error("'command' must be a non-empty list")
    if not endpoint_name:
        return tool_error("'endpoint_name' is required")
    if not isinstance(raw_markers, list):
        return tool_error("'markers' must be a list of strings")
    markers: list[str] = [str(m) for m in raw_markers]
    if long_interval < WATCHING_MIN_INTERVAL:
        return tool_error(f"'long_interval' must be >= {WATCHING_MIN_INTERVAL}")
    if short_interval < WATCHING_MIN_INTERVAL:
        return tool_error(f"'short_interval' must be >= {WATCHING_MIN_INTERVAL}")
    if short_interval > long_interval:
        return tool_error("'short_interval' must be <= long_interval")

    # ── 验证动态端点存在且属于当前 session ──
    from component.extools.dynamic_endpoint_tools import lookup_endpoint

    endpoint_info = lookup_endpoint(endpoint_name)
    if endpoint_info is None:
        return tool_error(f"Dynamic endpoint not found: {endpoint_name}")
    if endpoint_info.get("session_id") != session_id:
        return tool_error(
            f"Dynamic endpoint '{endpoint_name}' does not belong to session {session_id}",
        )

    # ── 拼接完整 POST URL ──
    from system.context import get_runtime_context

    ctx = get_runtime_context()
    agent_name: str = endpoint_info.get("agent_name", "")
    callback_url: str = (
        f"http://{ctx.gateway_host}:{ctx.gateway_port}"
        f"/dynamic/{session_id}/{agent_name}/{endpoint_name}"
    )

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
    log_dir = "ws:logs/background"
    log_path = f"{log_dir}/{task_id}.log"

    log_dir_real: str | None = _resolve_logical_path(log_dir)
    if not log_dir_real:
        return tool_error(f"Unable to resolve log directory: {log_dir}")

    Path(log_dir_real).mkdir(parents=True, exist_ok=True)
    log_file_real = str(Path(log_dir_real) / f"{task_id}.log")

    # ── 解析命令参数中的沙箱路径 ──
    resolved_parts: list[str] = []
    for part in cmd_parts:
        if any(part.startswith(p) for p in NAMESPACE_PREFIXES):
            try:
                r = _get_sandbox().resolve_read(part)
                resolved_parts.append(str(r.real))
            except SandboxError:
                resolved_parts.append(part)
        else:
            resolved_parts.append(part)

    # ── 启动后台进程（stdout 用 PIPE，由 reader 线程读取）──
    try:
        log_file = open(  # noqa: SIM115 — 由 reader 线程负责关闭
            log_file_real, "w", encoding=locale.getpreferredencoding(), errors="replace",
        )
        popen_kwargs: dict = {
            "cwd": cwd_real,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": False,
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = windows_process_group_flags()

        proc: subprocess.Popen = subprocess.Popen(resolved_parts, **popen_kwargs)

        # ── 创建 watching 运行时状态 ──
        watch = _WatchState(
            callback_url=callback_url,
            markers=markers,
            long_interval=long_interval,
            short_interval=short_interval,
            log_file=log_file,
        )

        _background_tasks[task_id] = {
            "proc": proc,
            "pid": proc.pid,
            "log_path": log_path,
            "log_file_real": log_file_real,
            "command": cmd_parts,
            "start_time": time.time(),
            "session_id": session_id,
            "watch": watch,
        }

        # ── 启动 reader + flusher 线程 ──
        watch.reader_thread = threading.Thread(
            target=_reader_loop, args=[task_id], daemon=True,
            name=f"watch-reader-{task_id}",
        )
        watch.flusher_thread = threading.Thread(
            target=_flusher_loop, args=[task_id], daemon=True,
            name=f"watch-flusher-{task_id}",
        )
        watch.reader_thread.start()
        watch.flusher_thread.start()

        logger.info(
            "Watching service started | task=%s pid=%d endpoint=%s markers=%s",
            task_id, proc.pid, endpoint_name, markers,
        )

        return tool_result(
            success=True,
            task_id=task_id,
            log_path=log_path,
            pid=proc.pid,
            command=cmd_parts,
            endpoint_name=endpoint_name,
            callback_url=callback_url,
            markers=markers,
            long_interval=long_interval,
            short_interval=short_interval,
            message=(
                f"Watching service started (task_id={task_id}, pid={proc.pid}). "
                f"Output will be automatically POSTed to {callback_url} every "
                f"{long_interval}s (or {short_interval}s when markers found). "
                f"You will receive [dynamic-endpoint] messages — do NOT poll the log file."
            ),
        )

    except Exception as exc:
        logger.exception("Failed to start watching service: %s", exc)
        return tool_error(f"Failed to start watching service: {exc}")


registry.register(
    name="start_watching_service",
    toolset="background",
    schema={
        # 启动后台进程并监视其 stdout/stderr，按自适应间隔将增量输出
        # POST 到指定的动态端点。进程输出同时写入日志文件。
        #
        # 重要：调用后无需主动轮询日志文件或使用 wait_cron + read_file
        # 组合检查输出。输出会自动通过动态端点回调为 [dynamic-endpoint]
        # 消息唤醒 Agent。只在需要完整历史记录时才用 read_file 读取 log_path。
        #
        # ## 前置条件
        # - command 必须为非空字符串列表。
        # - endpoint_name 必须是通过 register_dynamic_endpoint 注册的端点名称，
        #   且属于当前会话。
        # - markers 为字符串列表，用于子串匹配检测缓冲区内容。
        # - cwd 所在命名空间必须可读。
        # - 日志目录 ws:logs/background/ 必须可写。
        # - long_interval >= 3, short_interval >= 3, short_interval <= long_interval。
        #
        # ## 调用效果
        # 在后台启动子进程，reader 线程持续读取 stdout/stderr 并双写到
        # 内存缓冲区和日志文件。flusher 线程按自适应间隔检查缓冲区：
        #   - 缓冲区含任一 marker → 等待 short_interval 秒
        #   - 缓冲区不含 marker → 等待 long_interval 秒
        #   - 缓冲区为空 → 静默跳过不发送
        #   - 缓冲区非空 → 取出全部内容，清空缓冲区，POST 到动态端点
        # 进程退出时立即发送最终批次并附带退出码。
        # 非阻塞调用，立即返回 task_id。
        # Agent 会通过 [dynamic-endpoint] 消息自动收到增量输出，无需轮询。
        #
        # ## 返回
        # ```json
        # {"success": true, "task_id": "abc123", "log_path": "ws:logs/background/abc123.log", "pid": 1234, "command": ["..."], "endpoint_name": "my-endpoint", "callback_url": "http://127.0.0.1:8765/dynamic/...", "markers": ["ERROR"], "long_interval": 180, "short_interval": 12, "message": "..."}
        # ```
        #
        # ## 何时使用
        # - 需要持续监视长时间运行进程的输出。
        # - 需要在输出包含特定关键词时更快获得通知。
        # - 需要将进程输出发送到动态端点触发回调。
        #
        # ## 副作用/注意
        # - 进程在后台运行，可能产生文件系统或网络副作用，danger_level 为 dangerous。
        # - 每次调用需要用户审批。
        # - 输出会自动通过 [dynamic-endpoint] 消息回调，不要主动轮询日志文件。
        # - 日志文件保留完整记录，仅在需要回溯完整历史时用 read_file 读取。
        # - 进程退出后最终消息附带退出码。
        # - stop_background_service 停止时缓冲区内容通过返回值返回，不 POST。
        "description": """Start a background process and watch its stdout/stderr, posting incremental output to a dynamic endpoint at adaptive intervals.

**IMPORTANT: After calling this tool, do NOT poll the log file or use wait_cron + read_file to check output.** The output is automatically POSTed to the dynamic endpoint and you will receive a [dynamic-endpoint] message when new output arrives. Only use read_file on log_path when you need the complete historical record.

## Prerequisites
- command must be a non-empty list of strings.
- endpoint_name must be a dynamic endpoint registered via register_dynamic_endpoint belonging to the current session.
- markers is a list of strings used for substring matching against the buffer.
- The cwd namespace must be readable.
- The log directory ws:logs/background/ must be writable.
- long_interval >= 3, short_interval >= 3, short_interval <= long_interval.

## Effect
Launches a subprocess in the background. A reader thread continuously reads stdout/stderr and writes to both an in-memory buffer and a log file. A flusher thread checks the buffer at adaptive intervals:
- If the buffer contains any marker substring → wait short_interval seconds.
- If no marker is found → wait long_interval seconds.
- If the buffer is empty → skip silently, no POST.
- If the buffer is non-empty → take all content, clear the buffer, POST to the dynamic endpoint.
When the process exits, a final flush is triggered immediately with the exit code appended.
This is NON-BLOCKING: returns immediately with task_id.
You will receive output automatically via [dynamic-endpoint] messages — no polling needed.

## Returns
```json
{"success": true, "task_id": "abc123", "log_path": "ws:logs/background/abc123.log", "pid": 1234, "command": ["..."], "endpoint_name": "my-endpoint", "callback_url": "http://127.0.0.1:8765/dynamic/...", "markers": ["ERROR"], "long_interval": 180, "short_interval": 12, "message": "..."}
```

## When to Use
- Monitor output of a long-running process.
- Get faster notifications when output contains specific keywords.
- Send process output to a dynamic endpoint to trigger callbacks.
- Do NOT use this with wait_cron + read_file polling — the output comes to you automatically.

## Side Effects / Notes
- The process runs in the background and may cause filesystem or network side effects; danger_level is dangerous.
- Each invocation requires user approval.
- Output is automatically sent via [dynamic-endpoint] messages; do NOT poll the log file.
- The log file retains the complete record; use read_file only when you need full history.
- On process exit, a final message with the exit code is POSTed.
- When stopped via stop_background_service, the remaining buffer is returned in the tool result, not POSTed.""",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "array",
                    "items": {"type": "string"},
                    # 命令及参数列表，例如 ['python', '-m', 'http.server', '8080']。
                    "description": """Command and argument list, e.g. ['python', '-m', 'http.server', '8080'].""",
                },
                "endpoint_name": {
                    "type": "string",
                    # 动态端点名称，由 register_dynamic_endpoint 返回。
                    "description": """Name of the dynamic endpoint to POST output to (returned by register_dynamic_endpoint).""",
                },
                "markers": {
                    "type": "array",
                    "items": {"type": "string"},
                    # 特殊标识符列表，用于子串匹配检测缓冲区内容。
                    "description": """List of marker strings for substring matching against the output buffer. When any marker is found, the short_interval is used for the next flush cycle.""",
                },
                "long_interval": {
                    "type": "integer",
                    # 长间隔秒数（无标识符命中时使用），默认 180，最小 3。
                    "description": f"""Interval in seconds between flushes when no marker is found in the buffer. Default: {WATCHING_DEFAULT_LONG_INTERVAL}. Minimum: {WATCHING_MIN_INTERVAL}.""",
                    "default": WATCHING_DEFAULT_LONG_INTERVAL,
                },
                "short_interval": {
                    "type": "integer",
                    # 短间隔秒数（标识符命中后使用），默认 12，最小 3。
                    "description": f"""Interval in seconds between flushes when a marker is found in the buffer. Default: {WATCHING_DEFAULT_SHORT_INTERVAL}. Minimum: {WATCHING_MIN_INTERVAL}.""",
                    "default": WATCHING_DEFAULT_SHORT_INTERVAL,
                },
                "reason": {
                    "type": "string",
                    # 启动此 watching 服务的原因。
                    "description": """Reason for starting this watching service.""",
                },
                "cwd": {
                    "type": "string",
                    # 工作目录（ws: 命名空间，默认 'ws:'）。
                    "description": """Working directory (ws: namespace, default 'ws:').""",
                    "default": "ws:",
                },
            },
            "required": ["command", "endpoint_name", "markers", "reason"],
        },
    },
    handler=_handle_start_watching_service,
    is_async=True,
    emoji="👀",
    danger_level=ToolDangerLevel.dangerous,
    availability=ToolAvailability.MAIN | ToolAvailability.MULTI_AGENT,
)