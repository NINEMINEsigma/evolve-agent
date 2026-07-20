"""鼠标点击工具 — 在指定坐标模拟鼠标点击。

模块导入时通过 ``registry.register()`` 注册。

依赖 ``pyautogui``。通过 ``check_fn`` 检测可用性。
模块级设置 ``pyautogui.FAILSAFE = False`` 以避免自动化过程中
鼠标意外移至左上角触发的 FailSafeException。
"""

from __future__ import annotations

import logging
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)

_VALID_BUTTONS: set[str] = {"left", "right", "middle"}


def _try_import(module_name: str) -> bool:
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


def _check_pyautogui() -> bool:
    return _try_import("pyautogui")


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def _handle_mouse_click(args: dict[str, Any]) -> dict:
    """在指定坐标模拟鼠标点击。"""
    import pyautogui

    pyautogui.FAILSAFE = False

    x: int = int(args.get("x", -1))
    y: int = int(args.get("y", -1))
    button: str = str(args.get("button", "left")).lower().strip()
    clicks: int = int(args.get("clicks", 1))
    duration: float = float(args.get("duration", 0.0))

    if x < 0 or y < 0:
        return tool_error("x and y must be non-negative integers", x=x, y=y)
    if button not in _VALID_BUTTONS:
        return tool_error(
            f"button must be one of {sorted(_VALID_BUTTONS)}, got '{button}'",
            button=button,
        )
    if clicks < 1:
        return tool_error(f"clicks must be >= 1, got {clicks}", clicks=clicks)

    try:
        pyautogui.click(x=x, y=y, clicks=clicks, button=button, duration=duration)
    except Exception as exc:
        return tool_error(f"Mouse click failed: {exc}", x=x, y=y, button=button)

    logger.info("mouse_click | x=%d y=%d button=%s clicks=%d", x, y, button, clicks)

    return tool_result(
        success=True,
        x=x,
        y=y,
        button=button,
        clicks=clicks,
        duration=duration,
    )


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

registry.register(
    name="mouse_click",
    toolset="automation",
    schema={
        "description": """Simulate a mouse click at the specified screen coordinates.

## Prerequisites
- `pyautogui` must be installed.
- Windows only (screen coordinate system).

## Effect
Moves the mouse cursor to (x, y) and performs the specified number of clicks with the specified button. The move can be animated by setting `duration` > 0.

## Returns
```json
{"success": true, "x": 100, "y": 200, "button": "left", "clicks": 1, "duration": 0.0}
```

## When to Use
- After `template_match` returns a match — click the center of the matched region: `x + w/2`, `y + h/2`.
- To interact with UI elements at known screen positions.
- As part of an automation flow: `screen_capture` → `template_match` → `mouse_click`.

## Side Effects / Notes
- Directly controls the mouse — will move the cursor on screen.
- `pyautogui.FAILSAFE` is disabled to prevent accidental interruption when cursor reaches (0, 0).
- `duration` controls mouse movement animation time (seconds). 0 = instant.
- Coordinates are absolute screen coordinates (not relative to any window).""",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {
                    "type": "integer",
                    "description": "Screen X coordinate (absolute, non-negative).",
                },
                "y": {
                    "type": "integer",
                    "description": "Screen Y coordinate (absolute, non-negative).",
                },
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    "description": "Mouse button to click. Default: 'left'.",
                    "default": "left",
                },
                "clicks": {
                    "type": "integer",
                    "description": "Number of clicks. Default: 1.",
                    "default": 1,
                },
                "duration": {
                    "type": "number",
                    "description": "Duration of mouse movement to target in seconds. 0 = instant. Default: 0.0.",
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