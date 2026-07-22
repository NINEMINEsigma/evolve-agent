"""窗口焦点工具 — 通过 HWND 将指定窗口设为前台焦点。

模块导入时通过 ``registry.register()`` 注册。

仅兼容 Windows。使用 ``ctypes`` 调用 ``user32.dll`` Win32 API，
无第三方依赖。

使用前应先调用 ``window_find`` 获取目标窗口的 HWND。
"""

from __future__ import annotations

import ctypes
import logging
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Win32 API 常量
# ---------------------------------------------------------------------------

_SW_RESTORE: int = 9  # SW_RESTORE — 恢复最小化/最大化的窗口

_VK_MENU: int = 0x12  # VK_MENU — Alt 键
_KEYEVENTF_KEYUP: int = 0x0002  # keybd_event: 按键释放标志
_HWND_TOP: int = 0  # SetWindowPos: 置顶（非 TOPMOST）
_SWP_NOSIZE: int = 0x0001  # SetWindowPos: 保持大小
_SWP_NOMOVE: int = 0x0002  # SetWindowPos: 保持位置
_SWP_SHOWWINDOW: int = 0x0040  # SetWindowPos: 显示窗口


# ---------------------------------------------------------------------------
# 窗口焦点核心
# ---------------------------------------------------------------------------


def _bring_to_foreground(hwnd: int) -> bool:
    """强制将窗口置顶到前台。

    采用多级降级策略，确保对最小化、后台、被遮挡的窗口均有效：

    1. ``ShowWindow(SW_RESTORE)`` — 恢复最小化/最大化窗口
    2. ``BringWindowToTop`` — 提升 z-order
    3. 模拟 Alt 键按下/释放 — 解除 Windows 前台锁定
    4. ``SetForegroundWindow`` — 设为前台
    5. ``AttachThreadInput`` fallback — 附加线程输入后重试

    返回 ``SetForegroundWindow`` 的返回值（True 表示成功）。
    """
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    # ① 恢复窗口（最小化/最大化 → 正常）
    user32.ShowWindow(hwnd, _SW_RESTORE)

    # ② 提升 z-order
    user32.BringWindowToTop(hwnd)

    # ③ 模拟 Alt 键按下再释放，欺骗系统认为有用户输入，
    #    从而解除前台锁定，使 SetForegroundWindow 可以跨进程生效
    user32.keybd_event(_VK_MENU, 0, 0, 0)            # Alt down
    user32.keybd_event(_VK_MENU, 0, _KEYEVENTF_KEYUP, 0)  # Alt up

    # ④ 尝试设为前台
    success: bool = bool(user32.SetForegroundWindow(hwnd))

    # ⑤ 若失败，通过 AttachThreadInput 附加线程输入后重试
    if not success:
        current_tid = kernel32.GetCurrentThreadId()
        target_tid = user32.GetWindowThreadProcessId(hwnd, None)
        if current_tid != target_tid:
            user32.AttachThreadInput(target_tid, current_tid, True)
            try:
                user32.BringWindowToTop(hwnd)
                success = bool(user32.SetForegroundWindow(hwnd))
            finally:
                user32.AttachThreadInput(target_tid, current_tid, False)

    # ⑥ 最终兜底：用 SetWindowPos 强制 z-order 置顶并显示
    if not success:
        user32.SetWindowPos(
            hwnd, _HWND_TOP, 0, 0, 0, 0,
            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_SHOWWINDOW,
        )
        success = bool(user32.SetForegroundWindow(hwnd))

    return success


def _is_valid_window(hwnd: int) -> bool:
    """检查 HWND 是否指向一个存在的可见窗口。"""
    user32 = ctypes.windll.user32
    if not user32.IsWindow(hwnd):
        return False
    return bool(user32.IsWindowVisible(hwnd))


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def _handle_window_focus(args: dict[str, Any]) -> dict:
    """通过 HWND 将窗口设为前台焦点。"""
    hwnd: int = int(args.get("hwnd", 0))

    if hwnd <= 0:
        return tool_error("hwnd is required (positive integer)")

    if not _is_valid_window(hwnd):
        return tool_error(f"Invalid or invisible window: hwnd={hwnd}", hwnd=hwnd)

    focused: bool = _bring_to_foreground(hwnd)

    logger.info("window_focus | hwnd=%d focused=%s", hwnd, focused)

    return tool_result(
        success=True,
        hwnd=hwnd,
        foreground=focused,
    )


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

registry.register(
    name="window_focus",
    toolset="automation",
    schema={
        # 通过 HWND 将窗口设为前台焦点。
        # 前置条件：仅 Windows；需先用 window_find 获取 HWND。
        # 调用效果：恢复最小化/最大化窗口并强制置顶到前台，采用多级降级策略。
        # 返回值：hwnd、foreground（是否成功置顶）。
        # 典型场景：在执行需要窗口在前台的鼠标/键盘自动化之前调用。
        # 副作用：改变前台窗口，可能打断用户当前焦点。
        "description": """Bring a window to the foreground by its HWND.

## Prerequisites
- Windows only.
- Use `window_find` first to obtain the HWND of the target window.

## Effect
Restores the window (if minimized/maximized) and brings it to the foreground using `SetForegroundWindow`. Uses a multi-level fallback strategy: ShowWindow → BringWindowToTop → Alt key trick → SetForegroundWindow → AttachThreadInput → SetWindowPos.

## Returns
```json
{"success": true, "hwnd": 12345, "foreground": true}
```

## When to Use
- After `window_find` to bring the target window to the front.
- Before performing mouse/keyboard automation that requires the window to be in the foreground.
- To ensure the target window is active and visible.

## Side Effects / Notes
- Changes the foreground window, which may disrupt the user's current focus.
- Uses `AttachThreadInput` to bypass Windows foreground locking restrictions.
- The `foreground` field indicates whether `SetForegroundWindow` reported success.""",
        "parameters": {
            "type": "object",
            "properties": {
                "hwnd": {
                    "type": "integer",
                    # 窗口句柄（HWND），由 window_find 工具返回。
                    "description": "Window handle (HWND) obtained from `window_find`.",
                },
            },
            "required": ["hwnd"],
        },
    },
    handler=_handle_window_focus,
    emoji="🪟",
)