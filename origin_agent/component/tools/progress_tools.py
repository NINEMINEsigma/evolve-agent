"""任务进度条工具 — 在前端显示当前工作的进度。

模块导入时通过 ``registry.register()`` 注册 2 个工具：
  - ``set_task_progress``  — 创建或更新进度条
  - ``clear_task_progress`` — 清除进度条

进度条状态由前端维护，后端工具仅负责生成携带进度元数据的结果，
由 ``AgentLoop._execute_tool`` 检测后通过 ``task_progress`` 事件推送到前端。
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from abstract.tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)


# ── 内部状态：session_id → {task_id → progress_info} ─────────────────

_progress_registry: dict[str, dict[str, dict[str, Any]]] = {}


# ── handler ─────────────────────────────────────────────────────────


async def _handle_set_task_progress(args: dict[str, Any]) -> dict:
    """创建或更新前端进度条。

    参数：
        task_id:  进度条唯一标识（同一 task_id 会覆盖更新）
        label:    进度条标题/描述
        current:  当前已完成的工作量（整数）
        total:    总工作量（整数，必须 > 0）
        status:   可选状态文本，如 "downloading"、"compiling" 等
    """
    task_id: str = str(args.get("task_id", "")).strip()
    label: str = str(args.get("label", "")).strip()
    current: int = int(args.get("current", 0))
    total: int = int(args.get("total", 100))
    status: str = str(args.get("status", "")).strip()
    session_id: str = str(args.get("_session_id", ""))

    if not task_id:
        return tool_error("'task_id' is required")
    if total <= 0:
        return tool_error("'total' must be > 0")
    if current < 0:
        current = 0

    percent: float = min(100.0, (current / total) * 100.0) if total else 0.0

    info: dict[str, Any] = {
        "task_id": task_id,
        "label": label or task_id,
        "current": current,
        "total": total,
        "percent": round(percent, 1),
        "status": status or "running",
    }

    if session_id:
        _progress_registry.setdefault(session_id, {})[task_id] = info

    logger.info("Task progress updated | session=%s task=%s %d/%d (%.1f%%)",
                session_id, task_id, current, total, percent)

    return tool_result(**info)


async def _handle_clear_task_progress(args: dict[str, Any]) -> dict:
    """清除前端指定进度条。

    参数：
        task_id: 要清除的进度条标识。不提供则清除该会话所有进度条。
    """
    task_id: str = str(args.get("task_id", "")).strip()
    session_id: str = str(args.get("_session_id", ""))

    cleared: list[str] = []
    if session_id and session_id in _progress_registry:
        if task_id:
            if task_id in _progress_registry[session_id]:
                del _progress_registry[session_id][task_id]
                cleared.append(task_id)
        else:
            cleared = list(_progress_registry[session_id].keys())
            _progress_registry[session_id].clear()

    logger.info("Task progress cleared | session=%s tasks=%s", session_id, cleared)

    return tool_result(
        success=True,
        cleared=cleared,
        message=f"Cleared progress: {', '.join(cleared) if cleared else 'none'}"
    )


# ── 注册 ────────────────────────────────────────────────────────────

registry.register(
    name="set_task_progress",
    toolset="progress",
    schema={
        # Create or update a progress bar on the frontend to visualize the current task status.
        # Use this tool to keep the user informed about long-running operations (e.g., downloads, installations, builds).
        # The same task_id will overwrite the existing progress bar.
        # Returns the current progress metadata including computed percentage.
        "description": """Create or update a progress bar on the frontend to visualize the current task status.
Use this tool to keep the user informed about long-running operations (e.g., downloads, installations, builds).
The same task_id will overwrite the existing progress bar.

Returns the current progress metadata including computed percentage.""",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": """Unique identifier for this progress bar. Reusing the same ID updates it.""",
                },
                "label": {
                    "type": "string",
                    "description": """Human-readable title/description of the task.""",
                },
                "current": {
                    "type": "integer",
                    "description": """Current completed amount (integer).""",
                },
                "total": {
                    "type": "integer",
                    "description": """Total expected amount (integer, must be > 0).""",
                },
                "status": {
                    "type": "string",
                    "description": """Optional status text, e.g. 'downloading', 'compiling', 'waiting'.""",
                },
            },
            "required": ["task_id", "label", "current", "total"],
        },
    },
    handler=_handle_set_task_progress,
    is_async=True,
    emoji="📊",
    danger_level="readonly",
)

registry.register(
    name="clear_task_progress",
    toolset="progress",
    schema={
        # Remove a progress bar from the frontend.
        # If task_id is omitted, all progress bars for the current session are cleared.
        # Returns the list of cleared task IDs.
        "description": """Remove a progress bar from the frontend.
If task_id is omitted, all progress bars for the current session are cleared.

Returns the list of cleared task IDs.""",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": """task_id of the progress bar to clear. Omit to clear all.""",
                },
            },
            "required": [],
        },
    },
    handler=_handle_clear_task_progress,
    is_async=True,
    emoji="🧹",
    danger_level="readonly",
)