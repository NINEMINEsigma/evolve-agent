"""子窗口枚举工具 — 列出指定窗口的所有子窗口。

模块导入时通过 ``registry.register()`` 注册。

仅兼容 Windows。使用 ``ctypes`` 调用 ``user32.dll`` Win32 API，
无第三方依赖。

本工具用于获取窗口的子控件列表。某些窗口（如记事本）的顶层 HWND
不直接处理键盘输入，真正接收输入的是其子控件（如 Edit）。
使用本工具枚举子窗口后，可将子控件 HWND 传给 ``keyboard_type``、
``keyboard_press`` 等工具的 ``hwnd`` 参数，实现精准的后台输入。
"""

from __future__ import annotations

import ctypes
import logging
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Win32 API 常量 / 类型
# ---------------------------------------------------------------------------

_EnumChildProc = ctypes.WINFUNCTYPE(
    ctypes.c_bool,  # 返回值：True 继续枚举
    ctypes.c_void_p,  # hwnd
    ctypes.c_void_p,  # lParam
)


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


# ---------------------------------------------------------------------------
# Win32 函数 argtypes（一次性）
# ---------------------------------------------------------------------------

_user32 = ctypes.windll.user32

_user32.EnumChildWindows.argtypes = [
    ctypes.c_void_p,  # hwndParent
    _EnumChildProc,   # lpEnumFunc
    ctypes.c_void_p,  # lParam
]
_user32.EnumChildWindows.restype = ctypes.c_bool

_user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
_user32.IsWindowVisible.restype = ctypes.c_bool

_user32.IsWindowEnabled.argtypes = [ctypes.c_void_p]
_user32.IsWindowEnabled.restype = ctypes.c_bool

_user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
_user32.GetClassNameW.restype = ctypes.c_int

_user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
_user32.GetWindowTextW.restype = ctypes.c_int

_user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_RECT)]
_user32.GetWindowRect.restype = ctypes.c_bool

_user32.IsWindow.argtypes = [ctypes.c_void_p]
_user32.IsWindow.restype = ctypes.c_bool


# ---------------------------------------------------------------------------
# 子窗口信息采集
# ---------------------------------------------------------------------------


def _get_class_name(hwnd: int) -> str:
    """获取窗口类名。"""
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _get_window_text(hwnd: int) -> str:
    """获取窗口文本（标题 / 控件内容）。"""
    length = _user32.GetWindowTextLengthW(hwnd) if hasattr(_user32, "GetWindowTextLengthW") else 0
    # GetWindowTextLengthW 不在 argtypes 中，直接调用
    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _get_window_rect(hwnd: int) -> dict[str, int]:
    """获取窗口矩形坐标（屏幕坐标）。"""
    rect = _RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return {
        "left": rect.left,
        "top": rect.top,
        "right": rect.right,
        "bottom": rect.bottom,
    }


def enum_child_windows(parent_hwnd: int) -> list[dict[str, Any]]:
    """枚举指定窗口的所有直接子窗口（公共 API）。

    返回每个子窗口的 hwnd、class_name、text、visible、enabled、rect。
    """
    children: list[dict[str, Any]] = []

    def _enum_callback(hwnd: int, lparam: int) -> bool:
        cls = _get_class_name(hwnd)
        text = _get_window_text(hwnd)
        visible = bool(_user32.IsWindowVisible(hwnd))
        enabled = bool(_user32.IsWindowEnabled(hwnd))
        rect = _get_window_rect(hwnd)

        children.append({
            "hwnd": hwnd,
            "class_name": cls,
            "text": text,
            "visible": visible,
            "enabled": enabled,
            "rect": rect,
            "width": rect["right"] - rect["left"],
            "height": rect["bottom"] - rect["top"],
        })
        return True  # 继续枚举

    _user32.EnumChildWindows(parent_hwnd, _EnumChildProc(_enum_callback), 0)
    return children


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def _handle_window_enum_child(args: dict[str, Any]) -> dict:
    """枚举指定窗口的所有子窗口，返回子窗口列表。"""
    hwnd: int = int(args.get("hwnd", 0))

    if hwnd <= 0:
        return tool_error("hwnd is required and must be a positive integer")

    if not _user32.IsWindow(hwnd):
        return tool_error(f"Invalid window handle: hwnd={hwnd}", hwnd=hwnd)

    children = enum_child_windows(hwnd)

    if not children:
        logger.info("window_enum_child | hwnd=%d → no children", hwnd)
        return tool_result(
            success=True,
            hwnd=hwnd,
            count=0,
            children=[],
        )

    logger.info(
        "window_enum_child | hwnd=%d → %d child(ren)",
        hwnd, len(children),
    )

    return tool_result(
        success=True,
        hwnd=hwnd,
        count=len(children),
        children=children,
    )


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

registry.register(
    name="window_enum_child",
    toolset="automation",
    schema={
        # 枚举指定窗口的所有子窗口，返回每个子窗口的 HWND、类名、文本、可见性等。
        # 前置条件：仅 Windows；hwnd 必须是有效的窗口句柄（来自 window_find）。
        # 调用效果：遍历 hwnd 的所有直接子窗口，返回详细信息列表。
        # 返回值：children 列表（每个含 hwnd、class_name、text、visible、enabled、rect），count 子窗口数。
        # 典型场景：后台输入时，顶层窗口不处理 WM_CHAR，需要找到子控件（如 Edit）的 HWND。
        # 副作用：只读操作，不修改窗口状态。
        "description": """Enumerate child windows of a given window and return their details.

## Prerequisites
- Windows only.
- `hwnd` must be a valid window handle (obtain from `window_find`).

## Effect
Calls `EnumChildWindows` to list all direct child windows of the given `hwnd`. Returns each child's HWND, class name, text, visibility, enabled state, and screen rectangle.

## Returns
```json
{
  "success": true,
  "hwnd": 12345,
  "count": 1,
  "children": [
    {
      "hwnd": 67890,
      "class_name": "Edit",
      "text": "",
      "visible": true,
      "enabled": true,
      "rect": {"left": 110, "top": 110, "right": 890, "bottom": 690},
      "width": 780,
      "height": 580
    }
  ]
}
```

## When to Use
- **Before `keyboard_type` (background)**: The top-level window may not process `WM_CHAR` — only its child control (e.g. `Edit`) does. Use this tool to find the child's HWND, then pass it directly as the `hwnd` parameter to `keyboard_type`.
- **Before `keyboard_press` (background)**: Same reason — send key events to the child control, not the top-level window.
- **Before `mouse_click` (background)**: To inspect the structure of a complex window before clicking specific controls.
- **General window exploration**: To understand the UI structure of a target window.

## How to Pick the Right Child
- Look at `class_name`: `Edit` / `RichEdit` / `RichEdit20W` / `Scintilla` are typical text input controls.
- Look at `visible` and `enabled`: usually you want `visible: true` and `enabled: true`.
- Look at `rect` / `width` / `height`: the largest child is often the main content area.

## Side Effects / Notes
- Read-only operation — does not modify window state.
- Only direct children are enumerated. For nested children, call this tool again with a child's HWND.
- HWND values are valid only within the current session.""",
        "parameters": {
            "type": "object",
            "properties": {
                "hwnd": {
                    "type": "integer",
                    # 父窗口句柄（HWND），来自 window_find。枚举该窗口的所有直接子窗口。
                    "description": "Parent window handle (HWND) from `window_find`. All direct child windows of this window will be enumerated.",
                },
            },
            "required": ["hwnd"],
        },
    },
    handler=_handle_window_enum_child,
    emoji="📋",
)