"""窗口焦点工具 — 通过窗口标题定位 Win32 窗口并将其设为前台焦点。

模块导入时通过 ``registry.register()`` 注册。

仅兼容 Windows。使用 ``ctypes`` 调用 ``user32.dll`` Win32 API，
无第三方依赖。

共享函数 ``_find_window_by_title`` 供 ``screen_capture.py`` 复用。
"""

from __future__ import annotations

import ctypes
import logging
from typing import Any, Optional

from abstract.tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Win32 API 常量
# ---------------------------------------------------------------------------

_SW_RESTORE: int = 9  # SW_RESTORE — 恢复最小化/最大化的窗口
_GW_ENABLED: int = 2  # GW_ENABLED — 仅枚举可见且可用的窗口

# Win32 函数类型
_EnumWindowsProc = ctypes.WINFUNCTYPE(
    ctypes.c_bool,  # 返回值：True 继续枚举
    ctypes.c_void_p,  # hwnd
    ctypes.c_void_p,  # lParam
)


# ---------------------------------------------------------------------------
# 共享窗口查找函数
# ---------------------------------------------------------------------------


def _find_window_by_title(title: str) -> Optional[int]:
    """通过标题部分匹配查找顶层窗口 HWND。

    遍历所有可见顶层窗口，返回第一个标题中包含 *title* 的窗口 HWND。
    找不到时返回 None。
    """
    title_lower: str = title.lower()
    found_hwnd: list[int] = []

    def _enum_callback(hwnd: int, lparam: int) -> bool:
        # 跳过不可见窗口
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True

        # 获取窗口标题
        length: int = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)

        if title_lower in buffer.value.lower():
            found_hwnd.append(hwnd)
            return False  # 找到后停止枚举

        return True

    ctypes.windll.user32.EnumWindows(_EnumWindowsProc(_enum_callback), 0)

    return found_hwnd[0] if found_hwnd else None


# ---------------------------------------------------------------------------
# 窗口焦点 handler
# ---------------------------------------------------------------------------


def _handle_window_focus(args: dict[str, Any]) -> dict:
    """通过窗口标题定位窗口并将其设为前台焦点。"""
    window_title: str = str(args.get("window_title", "")).strip()

    if not window_title:
        return tool_error("window_title is required")

    hwnd: Optional[int] = _find_window_by_title(window_title)
    if hwnd is None:
        return tool_error(
            f"No window found with title containing '{window_title}'",
            window_title=window_title,
        )

    # 恢复窗口（如果最小化或最大化）
    ctypes.windll.user32.ShowWindow(hwnd, _SW_RESTORE)

    # SetForegroundWindow 在跨进程时可能失败（前台锁定限制）。
    # 通过 AttachThreadInput 绕过：附加目标窗口的线程输入到当前线程，
    # 使 SetForegroundWindow 获得权限。
    _attach_and_focus(hwnd)

    logger.info("window_focus | title='%s' hwnd=%d", window_title, hwnd)

    return tool_result(
        success=True,
        window_title=window_title,
        hwnd=hwnd,
    )


def _attach_and_focus(hwnd: int) -> None:
    """绕过 Windows 前台锁定限制，强制将窗口设为前台。

    通过 ``AttachThreadInput`` 将目标窗口的线程输入队列附加到当前线程，
    使 ``SetForegroundWindow`` 获得 ALTER 权限。
    """
    user32 = ctypes.windll.user32

    # 获取当前线程 ID 和目标窗口线程 ID
    current_tid = user32.GetCurrentThreadId()
    target_tid = user32.GetWindowThreadProcessId(hwnd, None)

    if current_tid != target_tid:
        # 附加线程输入
        user32.AttachThreadInput(target_tid, current_tid, True)
        try:
            user32.SetForegroundWindow(hwnd)
        finally:
            user32.AttachThreadInput(target_tid, current_tid, False)
    else:
        user32.SetForegroundWindow(hwnd)


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

registry.register(
    name="window_focus",
    toolset="automation",
    schema={
        "description": """Bring a window to the foreground by its title.

## Prerequisites
- Windows only.
- The target window must exist and be visible.

## Effect
Searches all visible top-level windows for one whose title contains the given `window_title` (case-insensitive partial match). If found, restores the window (if minimized/maximized) and brings it to the foreground using `SetForegroundWindow`.

## Returns
```json
{"success": true, "window_title": "...", "hwnd": 12345}
```

## When to Use
- Before taking a screenshot of a specific window.
- Before performing mouse/keyboard automation on a target application.
- To ensure the target window is active and visible.

## Side Effects / Notes
- Changes the foreground window, which may disrupt the user's current focus.
- Uses `AttachThreadInput` to bypass Windows foreground locking restrictions.
- If multiple windows match the title, the first one found is selected.""",
        "parameters": {
            "type": "object",
            "properties": {
                "window_title": {
                    "type": "string",
                    "description": "Partial window title to search for (case-insensitive). The first matching visible top-level window will be focused.",
                },
            },
            "required": ["window_title"],
        },
    },
    handler=_handle_window_focus,
    emoji="🪟",
)