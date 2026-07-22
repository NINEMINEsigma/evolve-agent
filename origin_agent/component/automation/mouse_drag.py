"""鼠标拖拽工具 — 支持屏幕坐标拖拽和窗口后台拖拽两种模式。

模块导入时通过 ``registry.register()`` 注册。

两种模式：
- **屏幕坐标模式**（不传 hwnd）：使用 ``pyautogui.moveTo`` + ``dragTo`` 在屏幕上
  执行拖拽。需要目标窗口在前台且未被遮挡。
- **后台拖拽模式**（传 hwnd）：使用 ``PostMessage`` 向指定窗口发送
  ``WM_LBUTTONDOWN`` → ``WM_MOUSEMOVE`` × N → ``WM_LBUTTONUP`` 消息序列。
  x1, y1, x2, y2 解释为窗口客户区坐标，与 ``screen_capture`` / ``template_match`` 衔接。
  窗口可被遮挡，无需在前台。

复用 ``mouse_click.py`` 中的 ``_BUTTON_MESSAGES`` 按键映射表。
依赖 ``pyautogui``（仅屏幕坐标模式需要）。通过 ``check_fn`` 检测可用性。
"""

from __future__ import annotations

import ctypes
import logging
import time
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result

# 复用 mouse_click 的按键→Win32消息映射表
from component.automation.mouse_click import _BUTTON_MESSAGES

logger = logging.getLogger(__name__)

_VALID_BUTTONS: set[str] = set(_BUTTON_MESSAGES.keys())

# ---------------------------------------------------------------------------
# Win32 API 常量（后台拖拽模式）
# ---------------------------------------------------------------------------

_WM_MOUSEMOVE: int = 0x0200


# ---------------------------------------------------------------------------
# 依赖检测
# ---------------------------------------------------------------------------


def _try_import(module_name: str) -> bool:
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


def _check_pyautogui() -> bool:
    return _try_import("pyautogui")


# ---------------------------------------------------------------------------
# 后台拖拽
# ---------------------------------------------------------------------------


def _post_drag(
    hwnd: int,
    x1: int, y1: int,
    x2: int, y2: int,
    button: str,
    steps: int,
    interval: float,
    hold: float,
) -> None:
    """通过 PostMessage 向窗口发送鼠标拖拽消息序列（后台拖拽）。

    在起点按下按键，沿直线路径发送 steps 个 WM_MOUSEMOVE，
    在终点保持 hold 秒后释放按键。坐标均为窗口客户区坐标。
    """
    user32 = ctypes.windll.user32
    down_msg, up_msg, mk_flag = _BUTTON_MESSAGES[button]

    # 起点按下
    lparam_start = (y1 << 16) | (x1 & 0xFFFF)
    user32.PostMessageW(hwnd, down_msg, mk_flag, lparam_start)

    # 沿路径发送 WM_MOUSEMOVE
    for i in range(1, steps + 1):
        t = i / steps
        mx = int(x1 + (x2 - x1) * t)
        my = int(y1 + (y2 - y1) * t)
        lparam = (my << 16) | (mx & 0xFFFF)
        user32.PostMessageW(hwnd, _WM_MOUSEMOVE, mk_flag, lparam)
        if interval > 0:
            time.sleep(interval)

    # 终点保持
    if hold > 0:
        time.sleep(hold)

    # 释放
    lparam_end = (y2 << 16) | (x2 & 0xFFFF)
    user32.PostMessageW(hwnd, up_msg, 0, lparam_end)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def _handle_mouse_drag(args: dict[str, Any]) -> dict:
    """模拟鼠标拖拽（屏幕坐标或窗口后台拖拽）。"""
    x1: int = int(args.get("x1", -1))
    y1: int = int(args.get("y1", -1))
    x2: int = int(args.get("x2", -1))
    y2: int = int(args.get("y2", -1))
    button: str = str(args.get("button", "left")).lower().strip()
    duration: float = float(args.get("duration", 0.5))
    hold: float = float(args.get("hold", 0.0))
    steps: int = int(args.get("steps", 20))
    interval: float = float(args.get("interval", 0.01))
    hwnd: int = int(args.get("hwnd", 0))

    if x1 < 0 or y1 < 0 or x2 < 0 or y2 < 0:
        return tool_error(
            "x1, y1, x2, y2 must be non-negative integers",
            x1=x1, y1=y1, x2=x2, y2=y2,
        )
    if button not in _VALID_BUTTONS:
        return tool_error(
            f"button must be one of {sorted(_VALID_BUTTONS)}, got '{button}'",
            button=button,
        )
    if steps < 1:
        return tool_error(f"steps must be >= 1, got {steps}", steps=steps)

    # ---- 后台拖拽模式 ----
    if hwnd > 0:
        if not ctypes.windll.user32.IsWindow(hwnd):
            return tool_error(f"Invalid window handle: hwnd={hwnd}", hwnd=hwnd)

        try:
            _post_drag(hwnd, x1, y1, x2, y2, button, steps, interval, hold)
        except Exception as exc:
            return tool_error(
                f"Background mouse drag failed: {exc}",
                hwnd=hwnd, x1=x1, y1=y1, x2=x2, y2=y2, button=button,
            )

        logger.info(
            "mouse_drag | hwnd=%d (%d,%d)→(%d,%d) button=%s steps=%d hold=%.2f (background)",
            hwnd, x1, y1, x2, y2, button, steps, hold,
        )

        return tool_result(
            success=True,
            hwnd=hwnd,
            x1=x1, y1=y1, x2=x2, y2=y2,
            button=button,
            steps=steps,
            interval=interval,
            hold=hold,
            mode="background",
        )

    # ---- 屏幕坐标模式 ----
    import pyautogui

    pyautogui.FAILSAFE = False

    try:
        pyautogui.moveTo(x1, y1, duration=0)
        pyautogui.mouseDown(x1, y1, button=button)
        pyautogui.moveTo(x2, y2, duration=duration)
        if hold > 0:
            time.sleep(hold)
        pyautogui.mouseUp(x2, y2, button=button)
    except Exception as exc:
        return tool_error(
            f"Mouse drag failed: {exc}",
            x1=x1, y1=y1, x2=x2, y2=y2, button=button,
        )

    logger.info(
        "mouse_drag | (%d,%d)→(%d,%d) button=%s duration=%.2f hold=%.2f (screen)",
        x1, y1, x2, y2, button, duration, hold,
    )

    return tool_result(
        success=True,
        x1=x1, y1=y1, x2=x2, y2=y2,
        button=button,
        duration=duration,
        hold=hold,
        mode="screen",
    )


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

registry.register(
    name="mouse_drag",
    toolset="automation",
    schema={
        # 模拟鼠标拖拽，支持屏幕坐标拖拽和窗口后台拖拽两种模式。
        # 前置条件：屏幕模式需 pyautogui；后台模式需先用 window_find 获取 HWND。
        # 调用效果：从起点 (x1,y1) 按住按键拖拽到终点 (x2,y2)，保持 hold 秒后释放。
        # 返回值：x1、y1、x2、y2、button、hold、mode（screen 或 background）。
        # 典型场景：拖拽文件、调整窗口大小、滑动列表、画布绘制等。
        # 副作用：屏幕模式移动鼠标光标；后台模式不移动光标。
        "description": """Simulate a mouse drag — screen coordinates or background window drag.

## Prerequisites
- `pyautogui` must be installed (screen mode only).
- Windows only.
- For background mode: use `window_find` first to obtain the HWND.

## Two Modes

### Screen mode (no `hwnd`)
Moves the cursor to (x1, y1), presses the button, drags to (x2, y2) over `duration` seconds, holds at the endpoint for `hold` seconds, then releases. The target window must be in the foreground and not obscured.

### Background mode (`hwnd` provided)
Uses `PostMessage` to send a sequence of `WM_LBUTTONDOWN` → `WM_MOUSEMOVE` × N → `WM_LBUTTONUP` directly to the target window. The window can be obscured or in the background. `x1, y1, x2, y2` are **window client-area coordinates** — the same coordinate system as `screen_capture` and `template_match`. `steps` controls the number of intermediate `WM_MOUSEMOVE` messages; `interval` controls the delay between each move message. After reaching the endpoint, waits `hold` seconds before sending the button-up message.

## Returns
```json
{"success": true, "x1": 100, "y1": 200, "x2": 300, "y2": 400, "button": "left", "duration": 0.5, "hold": 0.3, "mode": "screen"}
// or with hwnd:
{"success": true, "hwnd": 12345, "x1": 100, "y1": 200, "x2": 300, "y2": 400, "button": "left", "steps": 20, "interval": 0.01, "hold": 0.3, "mode": "background"}
```

## When to Use
- **Background mode**: Drag UI elements in an obscured window (e.g. scroll a list, resize a panel). Coordinates from `template_match` can be used directly.
- **Screen mode**: Drag files, resize windows, draw on canvas — when the target is in the foreground.
- Use `template_match` to find the draggable element's position, then drag from its center to the target location.
- Use `hold` to keep the button pressed at the endpoint before releasing — useful for drag-and-drop with delay, or when the target app needs time to register the drop.

## Side Effects / Notes
- Screen mode directly controls the mouse — will move the cursor on screen.
- Background mode does not move the cursor — the drag is sent via `PostMessage`.
- `pyautogui.FAILSAFE` is disabled in screen mode.
- Screen mode uses `duration` for drag time; background mode uses `steps` and `interval`.
- `hold` applies to both modes — the button is released after the hold delay.
- Some applications (DirectX games, certain Electron apps) may not respond to `PostMessage` drag messages. Use screen mode for those.
- Coordinates in background mode are relative to the window's client area (top-left = 0,0), matching `screen_capture` and `template_match` output.""",
        "parameters": {
            "type": "object",
            "properties": {
                "x1": {
                    "type": "integer",
                    # 起点X坐标。屏幕模式为绝对屏幕坐标；后台模式为窗口客户区坐标。
                    "description": "Start X coordinate. In screen mode: absolute screen position. In background mode: window client-area coordinate.",
                },
                "y1": {
                    "type": "integer",
                    # 起点Y坐标。屏幕模式为绝对屏幕坐标；后台模式为窗口客户区坐标。
                    "description": "Start Y coordinate. In screen mode: absolute screen position. In background mode: window client-area coordinate.",
                },
                "x2": {
                    "type": "integer",
                    # 终点X坐标。屏幕模式为绝对屏幕坐标；后台模式为窗口客户区坐标。
                    "description": "End X coordinate. In screen mode: absolute screen position. In background mode: window client-area coordinate.",
                },
                "y2": {
                    "type": "integer",
                    # 终点Y坐标。屏幕模式为绝对屏幕坐标；后台模式为窗口客户区坐标。
                    "description": "End Y coordinate. In screen mode: absolute screen position. In background mode: window client-area coordinate.",
                },
                "hwnd": {
                    "type": "integer",
                    # 窗口句柄（HWND）。传入时使用后台拖拽模式（PostMessage），省略时使用屏幕坐标模式（pyautogui）。
                    "description": "Window handle (HWND) from `window_find`. When provided, uses background drag mode (PostMessage). When omitted, uses screen coordinate mode (pyautogui).",
                },
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    # 鼠标按键，默认 left。
                    "description": "Mouse button to hold during drag. Default: 'left'.",
                    "default": "left",
                },
                "duration": {
                    "type": "number",
                    # 拖拽过程耗时（秒），仅屏幕模式生效，默认 0.5。
                    "description": "Duration of the drag movement in seconds (screen mode only). Default: 0.5.",
                    "default": 0.5,
                },
                "hold": {
                    "type": "number",
                    # 到达终点后保持按住的时间（秒），两种模式均生效，0 为立即释放，默认 0.0。
                    "description": "Time to hold the button at the endpoint before releasing (seconds). Applies to both modes. 0 = release immediately. Default: 0.0.",
                    "default": 0.0,
                },
                "steps": {
                    "type": "integer",
                    # 后台模式中间 WM_MOUSEMOVE 消息数量，默认 20。
                    "description": "Number of intermediate WM_MOUSEMOVE messages in background mode. More steps = smoother drag. Default: 20.",
                    "default": 20,
                },
                "interval": {
                    "type": "number",
                    # 后台模式每步之间的延迟（秒），默认 0.01。
                    "description": "Delay between each WM_MOUSEMOVE message in background mode (seconds). 0 = instant. Default: 0.01.",
                    "default": 0.01,
                },
            },
            "required": ["x1", "y1", "x2", "y2"],
        },
    },
    handler=_handle_mouse_drag,
    check_fn=_check_pyautogui,
    emoji="🖱️",
)