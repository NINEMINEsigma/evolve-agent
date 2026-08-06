"""后台任务注册表 — 被多方消费的公开 API 集中模块。

从 ``background_service.py`` 提取，供 ``gateway/server.py``、
``main.py``、``dynamic_endpoint_tools.py`` 等模块导入，
避免业务模块之间的循环依赖。

注册表数据结构：``_background_tasks[task_id]`` ->
``{proc, log_path, command, start_time, pid, session_id, [watch]}``
"""

from __future__ import annotations

import logging
import subprocess  # nosec
from typing import TYPE_CHECKING, Any

from entity.constant import SUBPROCESS_SOFT_CLEANUP_WAIT_TIME
from system.sandbox import _kill_proc_tree

if TYPE_CHECKING:
    from component.extools.background_service import _WatchState

logger = logging.getLogger(__name__)

# ── 内存注册表 ───────────────────────────────────────────────
# task_id -> {proc, log_path, command, start_time, pid, session_id, [watch]}

_background_tasks: dict[str, dict[str, Any]] = {}


# ── 公开 API ─────────────────────────────────────────────────


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


def stop_watching_by_endpoint(endpoint_name: str) -> int:
    """停止所有引用指定动态端点的 watching service。

    扫描 ``_background_tasks``，匹配 ``watch.callback_url`` 以
    ``/{endpoint_name}`` 结尾的 watching 任务，逐个调用
    ``stop_background_task`` 停止并返回数量。

    由 ``unregister_dynamic_endpoint`` 在端点注销时调用，
    确保端点消失后不再有任何 flusher 线程持续 POST。
    """
    suffix = f"/{endpoint_name}"
    stopped = 0
    for task_id, task in list(_background_tasks.items()):
        watch: _WatchState | None = task.get("watch")
        if watch is None:
            continue
        if not watch.callback_url.endswith(suffix):
            continue
        result = stop_background_task(task_id)
        if result.get("stopped"):
            stopped += 1
            logger.info(
                "Watching service stopped by endpoint unregister | task=%s endpoint=%s",
                task_id, endpoint_name,
            )
    return stopped