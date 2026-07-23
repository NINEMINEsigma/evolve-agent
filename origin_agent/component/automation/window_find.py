"""窗口查找工具 — 通过标题定位 Win32 窗口并返回 HWND。

模块导入时通过 ``registry.register()`` 注册。

仅兼容 Windows。使用 ``ctypes`` 调用 ``user32.dll`` Win32 API，
无第三方依赖。

本工具是 automation 工具链的入口：先通过标题获取 HWND，
后续的 ``window_focus`` / ``screen_capture`` / ``mouse_click`` 均以
HWND 为参数，不再各自按标题查找窗口。
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

_GW_ENABLED: int = 2  # GW_ENABLED — 仅枚举可见且可用的窗口

# Win32 函数类型
_EnumWindowsProc = ctypes.WINFUNCTYPE(
    ctypes.c_bool,  # 返回值：True 继续枚举
    ctypes.c_void_p,  # hwnd
    ctypes.c_void_p,  # lParam
)


# ---------------------------------------------------------------------------
# 窗口查找核心
# ---------------------------------------------------------------------------


class _WindowInfo(ctypes.Structure):
    """Win32 RECT 结构体，用于 GetWindowRect。"""

    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def find_windows_by_title(title: str) -> list[int]:
    """通过标题部分匹配查找所有顶层窗口 HWND（公共 API）。

    遍历所有可见顶层窗口，返回标题中包含 *title* 的全部窗口 HWND 列表。
    找不到时返回空列表。
    """
    title_lower: str = title.lower()
    found_hwnds: list[int] = []

    def _enum_callback(hwnd: int, lparam: int) -> bool:
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True

        length: int = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)

        if title_lower in buffer.value.lower():
            found_hwnds.append(hwnd)

        return True  # 始终继续枚举，收集所有匹配窗口

    ctypes.windll.user32.EnumWindows(_EnumWindowsProc(_enum_callback), 0)

    return found_hwnds


def _get_window_rect(hwnd: int) -> dict[str, int]:
    """获取窗口矩形坐标。"""
    rect = _WindowInfo()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return {
        "left": rect.left,
        "top": rect.top,
        "right": rect.right,
        "bottom": rect.bottom,
    }


def _get_window_title(hwnd: int) -> str:
    """获取窗口完整标题。"""
    length: int = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def _get_client_rect(hwnd: int) -> dict[str, int]:
    """获取窗口客户区尺寸。"""
    rect = _WindowInfo()
    ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rect))
    return {
        "left": rect.left,
        "top": rect.top,
        "right": rect.right,
        "bottom": rect.bottom,
    }


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def _handle_window_find(args: dict[str, Any]) -> dict:
    """通过窗口标题查找窗口，返回所有匹配窗口信息。"""
    window_title: str = str(args.get("window_title", "")).strip()

    if not window_title:
        return tool_error("window_title is required")

    hwnds: list[int] = find_windows_by_title(window_title)
    if not hwnds:
        return tool_error(
            f"No window found with title containing '{window_title}'",
            window_title=window_title,
        )

    # 构造所有匹配窗口的信息列表
    matches: list[dict[str, Any]] = []
    for hwnd in hwnds:
        title: str = _get_window_title(hwnd)
        rect: dict[str, int] = _get_window_rect(hwnd)
        client: dict[str, int] = _get_client_rect(hwnd)
        matches.append({
            "hwnd": hwnd,
            "title": title,
            "rect": rect,
            "width": rect["right"] - rect["left"],
            "height": rect["bottom"] - rect["top"],
            "client_width": client["right"] - client["left"],
            "client_height": client["bottom"] - client["top"],
        })

    # 第一个匹配用于向后兼容
    first: dict[str, Any] = matches[0]

    logger.info(
        "window_find | title='%s' → %d match(es), first hwnd=%d '%s' %dx%d (client %dx%d)",
        window_title, len(matches), first["hwnd"], first["title"],
        first["width"], first["height"], first["client_width"], first["client_height"],
    )

    return tool_result(
        success=True,
        query=window_title,
        count=len(matches),
        matches=matches,
    )


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

registry.register(
    name="window_find",
    toolset="automation",
    schema={
        # 通过窗口标题查找窗口，返回所有匹配窗口的 HWND 及尺寸信息。
        # 前置条件：仅 Windows；目标窗口必须存在且可见。
        # 调用效果：遍历所有可见顶层窗口，返回标题包含指定字符串的全部窗口。
        # 返回值：matches 列表（每个含 hwnd、title、rect、尺寸），count 匹配数。
        # 典型场景：自动化流程的第一步，获取 HWND 后传给其他工具。
        # 副作用：只读操作，不修改窗口状态。
        "description": """Find windows by title and return all matching HWNDs.

## Prerequisites
- Windows only.
- The target window must exist and be visible.

## Effect
Searches all visible top-level windows for ones whose title contains the given `window_title` (case-insensitive partial match). Returns all matching windows.

## Returns
```json
{
  "success": true,
  "query": "notepad",
  "count": 2,
  "matches": [
    {"hwnd": 12345, "title": "Notepad - Untitled", "rect": {"left": 100, "top": 100, "right": 900, "bottom": 700}, "width": 800, "height": 600, "client_width": 784, "client_height": 564},
    {"hwnd": 67890, "title": "Notepad - readme.txt", "rect": {"left": 200, "top": 200, "right": 1000, "bottom": 800}, "width": 800, "height": 600, "client_width": 784, "client_height": 564}
  ]
}
```

Inspect the `matches` array to pick the correct window by its full title, then pass that `hwnd` to `window_focus`, `screen_capture`, or `mouse_click`.

## When to Use
- As the first step in any automation flow to obtain the HWND.
- Before `screen_capture` to capture a specific window.
- Before `mouse_click` with background mode to click into an obscured window.
- Before `window_focus` to bring a specific window to the foreground.

## Side Effects / Notes
- Read-only operation — does not modify window state.
- Returns all matching windows; use `matches` to disambiguate when multiple windows share similar titles.
- HWND values are valid only within the current session; they may change if the window is closed and reopened.""",
        "parameters": {
            "type": "object",
            "properties": {
                "window_title": {
                    "type": "string",
                    # 窗口标题的部分匹配字符串（不区分大小写），返回所有匹配的可见顶层窗口。
                    "description": "Partial window title to search for (case-insensitive). All matching visible top-level windows will be returned.",
                },
            },
            "required": ["window_title"],
        },
    },
    handler=_handle_window_find,
    emoji="🔍",
)