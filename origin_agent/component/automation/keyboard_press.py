"""按键工具 — 模拟按键（如 Enter、Esc、Tab）及组合键。

模块导入时通过 ``registry.register()`` 注册。

依赖 ``pyautogui``。通过 ``check_fn`` 检测可用性。
当 key 包含 "+" 时自动拆分为组合键，使用 ``pyautogui.hotkey()``。
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


def _handle_keyboard_press(args: dict[str, Any]) -> dict:
    """模拟按键或组合键。"""
    import pyautogui

    pyautogui.FAILSAFE = False

    key: str = str(args.get("key", "")).strip()
    presses: int = int(args.get("presses", 1))

    if not key:
        return tool_error("key is required")
    if presses < 1:
        return tool_error(f"presses must be >= 1, got {presses}", presses=presses)

    try:
        if "+" in key:
            # 组合键：拆分为多个按键，用 hotkey 依次按下
            keys = [k.strip() for k in key.split("+") if k.strip()]
            if not keys:
                return tool_error(f"Invalid key combination: '{key}'")
            for _ in range(presses):
                pyautogui.hotkey(*keys)
        else:
            pyautogui.press(key, presses=presses)
    except Exception as exc:
        return tool_error(f"Key press failed: {exc}", key=key)

    logger.info("keyboard_press | key='%s' presses=%d", key, presses)

    return tool_result(
        success=True,
        key=key,
        presses=presses,
    )


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

registry.register(
    name="keyboard_press",
    toolset="automation",
    schema={
        "description": """Press a single key or a key combination.

## Prerequisites
- `pyautogui` must be installed.

## Effect
If `key` contains `+`, it is treated as a key combination and executed via `pyautogui.hotkey()` (e.g. "ctrl+c" presses Ctrl then C then releases both). Otherwise, `pyautogui.press()` is used for a single key.

## Returns
```json
{"success": true, "key": "enter", "presses": 1}
```

## When to Use
- Press Enter to confirm a dialog or submit a form.
- Press Escape to close a popup.
- Press "ctrl+c" to copy selected text.
- Press "ctrl+v" to paste clipboard content.
- Press "alt+tab" to switch windows.
- Press "ctrl+s" to save.

## Side Effects / Notes
- Directly controls the keyboard.
- `pyautogui.FAILSAFE` is disabled.
- Key names follow pyautogui conventions (e.g. "enter", "escape", "tab", "ctrl", "alt", "shift", "win", "space", "backspace", "delete").
- For combination keys, keys are pressed left-to-right and released in reverse order.""",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Key name (e.g. 'enter', 'escape', 'tab') or key combination with '+' separator (e.g. 'ctrl+c', 'alt+tab', 'ctrl+shift+s').",
                },
                "presses": {
                    "type": "integer",
                    "description": "Number of times to press the key. Default: 1.",
                    "default": 1,
                },
            },
            "required": ["key"],
        },
    },
    handler=_handle_keyboard_press,
    check_fn=_check_pyautogui,
    emoji="🔑",
)