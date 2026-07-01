"""任务进度条工具 — 在前端显示当前工作的进度。

模块导入时通过 ``registry.register()`` 注册 2 个工具：
  - ``set_task_progress``  — 创建或更新进度条
  - ``clear_task_progress`` — 清除进度条

进度条状态由前端维护，后端工具仅负责生成携带进度元数据的结果，
由 ``AgentLoop._execute_tool`` 检测后通过 ``task_progress`` 事件推送到前端。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Dict

from abstract.tools.registry import registry, tool_error, tool_result
from entity.puretype import ToolAvailability, ToolDangerLevel
from abstract.tools.ui_event_router import ui_event_router

if TYPE_CHECKING:
    from entry.agent_sink import AgentSink

logger = logging.getLogger(__name__)


# ── 内部状态：session_id → {task_id → progress_info} ─────────────────

_progress_registry: dict[str, dict[str, dict[str, Any]]] = {}


# ── emit handler ────────────────────────────────────────────────


async def _emit_task_progress(
    result: Any, sink: AgentSink, session_id: str, tool_name: str,
) -> None:
    """将 progress tool result 推送到前端。"""
    payload = json.dumps(result, ensure_ascii=False)
    await sink.emit_progress(session_id, tool_name, payload)


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
        # 创建或更新前端进度条以可视化当前任务状态。
        # 任何可拆分为离散阶段的串行任务都应积极使用此工具（多文件编辑、批量下载、分步构建、多阶段操作）。
        #
        # ## 调用效果
        # 创建或更新一个由 `task_id` 标识的进度条。复用同一 `task_id` 会覆盖已有进度条。百分比自动计算为 `current / total * 100`，上限 100%。
        #
        # ## 返回
        # ```json
        # {"task_id": "...", "label": "...", "current": 3, "total": 10, "percent": 30.0, "status": "running"}
        # ```
        #
        # ## 何时使用
        # - 任何可拆分为离散阶段的串行任务（多文件编辑、批量下载、分步构建、多阶段操作）。
        # - 增量反馈能降低用户不确定性的长时间操作。
        #
        # ## 副作用/注意
        # - 任务确定结束后应调用 `clear_task_progress` 清理进度条。
        # - 进度条限定在会话范围内，会话结束时自动清除。
        # - `current` 被 clamp 到 >= 0；`total` 必须 > 0。
        # - 若 `label` 为空，`task_id` 被用作显示标签。
        # - `status` 省略时默认为 'running'。
        "description": """Create or update a frontend progress bar to visualize the current task status.
This tool SHOULD be used proactively for any serial task that can be divided into discrete stages (multi-file edits, batch downloads, step-by-step builds, multi-phase operations).

## Effect
Creates or updates a progress bar identified by `task_id`. Reusing the same `task_id` overwrites the previous bar. Percentage is auto-computed as `current / total * 100`, capped at 100%.

## Returns
```json
{"task_id": "...", "label": "...", "current": 3, "total": 10, "percent": 30.0, "status": "running"}
```

## When to Use
- Any serial task that can be divided into discrete stages (multi-file edits, batch downloads, step-by-step builds, multi-phase operations).
- Long-running operations where incremental feedback reduces user uncertainty.

## Side Effects / Notes
- After the task is confirmed complete, call `clear_task_progress` to clean up the progress bar.
- Progress bars are session-scoped and auto-cleared when the session ends.
- `current` is clamped to >= 0; `total` must be > 0.
- If `label` is empty, `task_id` is used as the display label.
- `status` defaults to 'running' if omitted.""",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    # 此进度条的唯一标识。复用同一 ID 更新已有进度条。必须非空。
                    "description": """Unique identifier for this progress bar. Reusing the same ID updates the existing bar. Must be non-empty.""",
                },
                "label": {
                    "type": "string",
                    # 前端进度条上显示的标题。为空或省略时回退为 task_id。
                    "description": """Display title shown on the frontend bar. Falls back to task_id if empty or omitted.""",
                },
                "current": {
                    "type": "integer",
                    # 已完成单元数。非负整数；负值被 clamp 到 0。
                    "description": """Number of completed units. Non-negative integer; negative values are clamped to 0.""",
                },
                "total": {
                    "type": "integer",
                    # 预期总单元数。必须为正整数（> 0）。
                    "description": """Total number of units expected. Must be a positive integer (> 0).""",
                },
                "status": {
                    "type": "string",
                    # 可选状态文本（如 'downloading'、'compiling'）。默认为 'running'。
                    "description": """Optional status text (e.g. 'downloading', 'compiling'). Defaults to 'running'.""",
                },
            },
            "required": ["task_id", "label", "current", "total"],
        },
    },
    handler=_handle_set_task_progress,
    is_async=True,
    emoji="📊",
    danger_level=ToolDangerLevel.readonly,
    availability=ToolAvailability.MAIN,
)
ui_event_router.register("set_task_progress", _emit_task_progress)

registry.register(
    name="clear_task_progress",
    toolset="progress",
    schema={
        # 从当前会话移除一个或全部进度条。
        # 提供 `task_id` 则仅移除该进度条；省略或为空则移除当前会话全部进度条。
        #
        # ## 前置条件
        # 当前会话中应存在对应的进度条。调用不存在的 `task_id` 不报错（no-op）。
        #
        # ## 调用效果
        # 若提供了 `task_id` 且非空，仅移除该特定进度条。若省略或为空，移除当前会话的全部进度条。
        #
        # ## 返回
        # ```json
        # {"success": true, "cleared": ["task_1"], "message": "Cleared progress: task_1"}
        # ```
        #
        # ## 何时使用
        # - 任务确定完成后清理关联的进度条。
        # - 任务取消或中止后移除残留的进度指示。
        # - 开始新阶段时清除全部进度条以重置界面。
        #
        # ## 副作用/注意
        # - 清除不存在的 `task_id` 为 no-op（不返回错误）。
        # - 进度条在会话结束时自动清除；显式调用仍推荐用于即时界面清理。
        "description": """Remove one or all progress bars from the current session.
Provide `task_id` to remove only that bar; omit or leave empty to remove all progress bars for the current session.

## Prerequisites
The corresponding progress bar should exist in the current session. Calling with a non-existent `task_id` is a no-op (no error returned).

## Effect
If `task_id` is provided and non-empty, removes only that specific bar. If omitted or empty, removes ALL progress bars for the current session.

## Returns
```json
{"success": true, "cleared": ["task_1"], "message": "Cleared progress: task_1"}
```

## When to Use
- After a task is confirmed complete, clean up the associated progress bar.
- After a task is cancelled or aborted, remove stale progress indicators.
- When starting a new phase, clear all bars to reset the UI.

## Side Effects / Notes
- Clearing a non-existent `task_id` is a no-op (no error returned).
- Progress bars are auto-cleared when the session ends; explicit calls are still recommended for immediate UI cleanup.""",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    # 要清除的进度条标识。省略或为空则清除当前会话全部进度条。
                    "description": """Identifier of the progress bar to clear. Omit or leave empty to clear all progress bars for the current session.""",
                },
            },
            "required": [],
        },
    },
    handler=_handle_clear_task_progress,
    is_async=True,
    emoji="🧹",
    danger_level=ToolDangerLevel.readonly,
    availability=ToolAvailability.MAIN,
)
ui_event_router.register("clear_task_progress", _emit_task_progress)