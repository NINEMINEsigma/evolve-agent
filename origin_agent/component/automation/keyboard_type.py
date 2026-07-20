"""键盘输入工具 — 模拟键盘输入文本。

模块导入时通过 ``registry.register()`` 注册。

依赖 ``pyautogui``。通过 ``check_fn`` 检测可用性。
使用 ``pyautogui.write()`` 支持 Unicode 文本输入。
"""

from __future__ import annotations

import logging
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)


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


def _handle_keyboard_type(args: dict[str, Any]) -> dict:
    """模拟键盘输入文本。"""
    import pyautogui

    pyautogui.FAILSAFE = False

    text: str = str(args.get("text", ""))
    interval: float = float(args.get("interval", 0.0))

    if not text:
        return tool_error("text is required and must be non-empty")

    try:
        pyautogui.write(text, interval=interval)
    except Exception as exc:
        return tool_error(f"Keyboard input failed: {exc}", text=text[:100])

    logger.info("keyboard_type | length=%d interval=%.2f", len(text), interval)

    return tool_result(
        success=True,
        text=text,
        length=len(text),
        interval=interval,
    )


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

registry.register(
    name="keyboard_type",
    toolset="automation",
    schema={
        "description": """Type text via simulated keyboard input.

## Prerequisites
- `pyautogui` must be installed.
- The target input field must be focused (use `mouse_click` to click into it first).

## Effect
Types the given text character by character at the current cursor position. Supports Unicode text via `pyautogui.write()`.

## Returns
```json
{"success": true, "text": "hello world", "length": 11, "interval": 0.0}
```

## When to Use
- After clicking into an input field with `mouse_click`.
- To fill in forms, search boxes, or text areas.
- To enter commands in a terminal or console.

## Side Effects / Notes
- Directly controls the keyboard — will type into whatever field currently has focus.
- `pyautogui.FAILSAFE` is disabled.
- For non-ASCII text (CJK, emoji), `pyautogui.write()` sends Unicode characters. If the target app does not accept Unicode input, consider using `keyboard_press` with Ctrl+V after copying text to clipboard.
- `interval` controls the delay between each keystroke (seconds). 0 = instant.""",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to type. Supports Unicode characters.",
                },
                "interval": {
                    "type": "number",
                    "description": "Delay between each keystroke in seconds. 0 = instant. Default: 0.0.",
                    "default": 0.0,
                },
            },
            "required": ["text"],
        },
    },
    handler=_handle_keyboard_type,
    check_fn=_check_pyautogui,
    emoji="⌨️",
)