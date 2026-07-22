"""鼠标点击工具 — 支持屏幕坐标点击和窗口后台点击两种模式。

模块导入时通过 ``registry.register()`` 注册。

两种模式：
- **屏幕坐标模式**（不传 hwnd）：使用 ``pyautogui.click(x, y)`` 在屏幕绝对坐标点击。
  需要目标窗口在前台且未被遮挡。
- **后台点击模式**（传 hwnd）：使用 ``PostMessage`` 向指定窗口发送鼠标消息。
  x, y 解释为窗口客户区坐标，与 ``screen_capture`` / ``template_match`` 衔接。
  窗口可被遮挡，无需在前台。

依赖 ``pyautogui``（仅屏幕坐标模式需要）。通过 ``check_fn`` 检测可用性。
模块级设置 ``pyautogui.FAILSAFE = False`` 以避免自动化过程中
鼠标意外移至左上角触发的 FailSafeException。
"""

from __future__ import annotations

import ctypes
import logging
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)

_VALID_BUTTONS: set[str] = {"left", "right", "middle"}

# ---------------------------------------------------------------------------
# Win32 API 常量（后台点击模式）
# ---------------------------------------------------------------------------

_WM_LBUTTONDOWN: int = 0x0201
_WM_LBUTTONUP: int = 0x0202
_WM_RBUTTONDOWN: int = 0x0204
_WM_RBUTTONUP: int = 0x0205
_WM_MBUTTONDOWN: int = 0x0207
_WM_MBUTTONUP: int = 0x0208

_MK_LBUTTON: int = 0x0001
_MK_RBUTTON: int = 0x0002
_MK_MBUTTON: int = 0x0010

# button → (down message, up message, MK_* flag)
_BUTTON_MESSAGES: dict[str, tuple[int, int, int]] = {
    "left": (_WM_LBUTTONDOWN, _WM_LBUTTONUP, _MK_LBUTTON),
    "right": (_WM_RBUTTONDOWN, _WM_RBUTTONUP, _MK_RBUTTON),
    "middle": (_WM_MBUTTONDOWN, _WM_MBUTTONUP, _MK_MBUTTON),
}


def _try_import(module_name: str) -> bool:
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


def _check_pyautogui() -> bool:
    return _try_import("pyautogui")


# ---------------------------------------------------------------------------
# 后台点击
# ---------------------------------------------------------------------------


def _post_click(hwnd: int, x: int, y: int, button: str, clicks: int) -> bool:
    """通过 PostMessage 向窗口发送鼠标点击消息（后台点击）。

    x, y 为窗口客户区坐标。窗口可被遮挡。
    """
    user32 = ctypes.windll.user32
    down_msg, up_msg, mk_flag = _BUTTON_MESSAGES[button]
    lparam = (y << 16) | (x & 0xFFFF)

    for _ in range(clicks):
        user32.PostMessageW(hwnd, down_msg, mk_flag, lparam)
        user32.PostMessageW(hwnd, up_msg, 0, lparam)

    return True


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def _handle_mouse_click(args: dict[str, Any]) -> dict:
    """在指定坐标模拟鼠标点击（屏幕坐标或窗口后台点击）。"""
    x: int = int(args.get("x", -1))
    y: int = int(args.get("y", -1))
    button: str = str(args.get("button", "left")).lower().strip()
    clicks: int = int(args.get("clicks", 1))
    duration: float = float(args.get("duration", 0.0))
    hwnd: int = int(args.get("hwnd", 0))

    if x < 0 or y < 0:
        return tool_error("x and y must be non-negative integers", x=x, y=y)
    if button not in _VALID_BUTTONS:
        return tool_error(
            f"button must be one of {sorted(_VALID_BUTTONS)}, got '{button}'",
            button=button,
        )
    if clicks < 1:
        return tool_error(f"clicks must be >= 1, got {clicks}", clicks=clicks)

    # ---- 后台点击模式 ----
    if hwnd > 0:
        if not ctypes.windll.user32.IsWindow(hwnd):
            return tool_error(f"Invalid window handle: hwnd={hwnd}", hwnd=hwnd)

        try:
            _post_click(hwnd, x, y, button, clicks)
        except Exception as exc:
            return tool_error(
                f"Background mouse click failed: {exc}",
                hwnd=hwnd, x=x, y=y, button=button,
            )

        logger.info(
            "mouse_click | hwnd=%d x=%d y=%d button=%s clicks=%d (background)",
            hwnd, x, y, button, clicks,
        )

        return tool_result(
            success=True,
            hwnd=hwnd,
            x=x,
            y=y,
            button=button,
            clicks=clicks,
            mode="background",
        )

    # ---- 屏幕坐标模式 ----
    import pyautogui

    pyautogui.FAILSAFE = False

    try:
        pyautogui.click(x=x, y=y, clicks=clicks, button=button, duration=duration)
    except Exception as exc:
        return tool_error(f"Mouse click failed: {exc}", x=x, y=y, button=button)

    logger.info("mouse_click | x=%d y=%d button=%s clicks=%d (screen)", x, y, button, clicks)

    return tool_result(
        success=True,
        x=x,
        y=y,
        button=button,
        clicks=clicks,
        duration=duration,
        mode="screen",
    )


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

registry.register(
    name="mouse_click",
    toolset="automation",
    schema={
        # 模拟鼠标点击，支持屏幕坐标点击和窗口后台点击两种模式。
        # 前置条件：屏幕模式需 pyautogui；后台模式需先用 window_find 获取 HWND。
        # 调用效果：屏幕模式移动光标到坐标并点击；后台模式通过 PostMessage 发送点击消息。
        # 返回值：x、y、button、clicks、mode（screen 或 background）。
        # 典型场景：后台模式用于被遮挡窗口的点击；屏幕模式用于前台窗口。
        # 副作用：屏幕模式移动鼠标光标；后台模式不移动光标。
        "description": """Simulate a mouse click — screen coordinates or background window click.

## Prerequisites
- `pyautogui` must be installed (screen mode only).
- Windows only.
- For background mode: use `window_find` first to obtain the HWND.

## Two Modes

### Screen mode (no `hwnd`)
Moves the mouse cursor to (x, y) and performs the specified number of clicks with the specified button. The target window must be in the foreground and not obscured. `duration` controls mouse movement animation.

### Background mode (`hwnd` provided)
Uses `PostMessage` to send mouse click messages directly to the target window. The window can be obscured or in the background. `x` and `y` are interpreted as **window client-area coordinates** — the same coordinate system as `screen_capture` and `template_match`. `duration` is not used in this mode.

## Returns
```json
{"success": true, "x": 100, "y": 200, "button": "left", "clicks": 1, "mode": "screen"}
// or with hwnd:
{"success": true, "hwnd": 12345, "x": 100, "y": 200, "button": "left", "clicks": 1, "mode": "background"}
```

## When to Use
- **Background mode**: After `window_find` → `screen_capture` → `template_match`, click the center of the matched region: `x + w/2`, `y + h/2`. The coordinates from `template_match` are already in window client-area coordinates, so no conversion is needed.
- **Screen mode**: To interact with UI elements at known screen positions when the target is guaranteed to be in the foreground.

## Side Effects / Notes
- Screen mode directly controls the mouse — will move the cursor on screen.
- Background mode does not move the cursor — the click is sent via `PostMessage`.
- `pyautogui.FAILSAFE` is disabled in screen mode.
- Background mode `duration` is ignored (no mouse movement animation).
- Some applications (DirectX games, certain Electron apps) may not respond to `PostMessage` mouse messages. Use screen mode for those.
- Coordinates in background mode are relative to the window's client area (top-left = 0,0), matching `screen_capture` and `template_match` output.""",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {
                    "type": "integer",
                    # X 坐标。屏幕模式为绝对屏幕坐标；后台模式为窗口客户区坐标。
                    "description": "X coordinate. In screen mode: absolute screen position. In background mode: window client-area coordinate.",
                },
                "y": {
                    "type": "integer",
                    # Y 坐标。屏幕模式为绝对屏幕坐标；后台模式为窗口客户区坐标。
                    "description": "Y coordinate. In screen mode: absolute screen position. In background mode: window client-area coordinate.",
                },
                "hwnd": {
                    "type": "integer",
                    # 窗口句柄（HWND）。传入时使用后台点击模式（PostMessage），省略时使用屏幕坐标模式（pyautogui）。
                    "description": "Window handle (HWND) from `window_find`. When provided, uses background click mode (PostMessage). When omitted, uses screen coordinate mode (pyautogui).",
                },
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    # 鼠标按键，默认 left。
                    "description": "Mouse button to click. Default: 'left'.",
                    "default": "left",
                },
                "clicks": {
                    "type": "integer",
                    # 点击次数，默认 1。
                    "description": "Number of clicks. Default: 1.",
                    "default": 1,
                },
                "duration": {
                    "type": "number",
                    # 鼠标移动到目标的动画时长（秒），仅屏幕模式生效，0 为瞬移，默认 0.0。
                    "description": "Duration of mouse movement to target in seconds (screen mode only). 0 = instant. Default: 0.0.",
                    "default": 0.0,
                },
            },
            "required": ["x", "y"],
        },
    },
    handler=_handle_mouse_click,
    check_fn=_check_pyautogui,
    emoji="🖱️",
)