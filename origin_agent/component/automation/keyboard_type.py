"""键盘输入工具 — 模拟键盘输入文本。

模块导入时通过 ``registry.register()`` 注册。

两种模式：
- **前台模式**（不传 hwnd）：使用 ``pyautogui.write()`` 逐字符输入，
  需要目标窗口在前台且输入框已聚焦。
- **后台模式**（传 hwnd）：使用 ``PostMessage`` 向指定窗口发送
  ``WM_CHAR`` 消息逐字符输入，窗口可被遮挡，无需在前台。
  支持 Unicode 文本。

依赖 ``pyautogui``（仅前台模式需要）。通过 ``check_fn`` 检测可用性。
"""

from __future__ import annotations

import ctypes
import logging
import time
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
# Win32 API 常量（后台文本输入模式）
# ---------------------------------------------------------------------------

_WM_CHAR: int = 0x0102


def _post_text(hwnd: int, text: str, interval: float) -> bool:
    """通过 PostMessage 向窗口发送 WM_CHAR 消息（后台文本输入）。

    逐字符发送 Unicode 码点，窗口可被遮挡，无需在前台。
    """
    user32 = ctypes.windll.user32
    for char in text:
        user32.PostMessageW(hwnd, _WM_CHAR, ord(char), 0)
        if interval > 0:
            time.sleep(interval)
    return True


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def _handle_keyboard_type(args: dict[str, Any]) -> dict:
    """模拟键盘输入文本（前台 pyautogui 或后台 PostMessage）。"""
    text: str = str(args.get("text", ""))
    interval: float = float(args.get("interval", 0.0))
    hwnd: int = int(args.get("hwnd", 0))

    if not text:
        return tool_error("text is required and must be non-empty")

    # ---- 后台文本输入模式 ----
    if hwnd > 0:
        if not ctypes.windll.user32.IsWindow(hwnd):
            return tool_error(f"Invalid window handle: hwnd={hwnd}", hwnd=hwnd)

        try:
            _post_text(hwnd, text, interval)
        except Exception as exc:
            return tool_error(
                f"Background keyboard input failed: {exc}",
                text=text[:100], hwnd=hwnd,
            )

        logger.info(
            "keyboard_type | hwnd=%d length=%d interval=%.2f (background)",
            hwnd, len(text), interval,
        )

        return tool_result(
            success=True,
            text=text,
            length=len(text),
            interval=interval,
            hwnd=hwnd,
            mode="background",
        )

    # ---- 前台文本输入模式 ----
    import pyautogui

    pyautogui.FAILSAFE = False

    try:
        pyautogui.write(text, interval=interval)
    except Exception as exc:
        return tool_error(f"Keyboard input failed: {exc}", text=text[:100])

    logger.info("keyboard_type | length=%d interval=%.2f (foreground)", len(text), interval)

    return tool_result(
        success=True,
        text=text,
        length=len(text),
        interval=interval,
        mode="foreground",
    )


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

registry.register(
    name="keyboard_type",
    toolset="automation",
    schema={
        # 模拟键盘输入文本，支持前台 pyautogui 和后台 PostMessage 两种模式。
        # 前置条件：前台模式需 pyautogui 且输入框已聚焦；后台模式需先用 window_find 获取 HWND。
        # 调用效果：前台模式用 pyautogui.write 逐字符输入；后台模式通过 PostMessage 发送 WM_CHAR。
        # 返回值：text、length、interval、mode（foreground 或 background）。
        # 典型场景：后台模式用于被遮挡窗口的文本输入；前台模式用于前台窗口。
        # 副作用：前台模式直接控制键盘；后台模式不需要前台焦点。
        "description": """Type text via simulated keyboard input.

## Prerequisites
- `pyautogui` must be installed (foreground mode only).
- The target input field must be focused (use `mouse_click` to click into it first).
- For background mode: use `window_find` first to obtain the HWND.

## Two Modes

### Foreground mode (no `hwnd`)
Types the given text character by character at the current cursor position using `pyautogui.write()`. Supports Unicode text. The target window must be in the foreground.

### Background mode (`hwnd` provided)
Sends `WM_CHAR` messages via `PostMessage` to the target window. Each character is sent as its Unicode code point. The window can be obscured or in the background — no foreground focus needed.

## Returns
```json
{"success": true, "text": "hello world", "length": 11, "interval": 0.0, "mode": "foreground"}
// or with hwnd:
{"success": true, "text": "hello world", "length": 11, "interval": 0.0, "hwnd": 12345, "mode": "background"}
```

## When to Use
- **Background mode**: After `window_find` → `mouse_click` (background) to focus an input field, then type text without stealing foreground focus. Ideal for batch automation where disrupting the user's focus is undesirable.
- **Foreground mode**: After clicking into an input field with `mouse_click`. To fill in forms, search boxes, or text areas. To enter commands in a terminal or console.

## Side Effects / Notes
- Foreground mode directly controls the keyboard — will type into whatever field currently has focus. `pyautogui.FAILSAFE` is disabled.
- Background mode does not require foreground focus — text is sent via `PostMessage` `WM_CHAR`.
- For non-ASCII text (CJK, emoji), both modes support Unicode. If the target app does not accept Unicode input in foreground mode, consider using `keyboard_press` with Ctrl+V after copying text to clipboard.
- `interval` controls the delay between each keystroke (seconds). 0 = instant.
- Some applications (DirectX games, certain Electron apps) may not respond to `PostMessage` `WM_CHAR` messages. Use foreground mode for those.""",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    # 要输入的文本，支持 Unicode 字符。
                    "description": "The text to type. Supports Unicode characters.",
                },
                "interval": {
                    "type": "number",
                    # 每次按键之间的延迟（秒），0 为即时，默认 0.0。
                    "description": "Delay between each keystroke in seconds. 0 = instant. Default: 0.0.",
                    "default": 0.0,
                },
                "hwnd": {
                    "type": "integer",
                    # 窗口句柄（HWND）。传入时使用后台文本输入模式（PostMessage WM_CHAR），省略时使用前台模式（pyautogui）。
                    "description": "Window handle (HWND) from `window_find`. When provided, uses background typing mode (PostMessage WM_CHAR). When omitted, uses foreground mode (pyautogui).",
                },
            },
            "required": ["text"],
        },
    },
    handler=_handle_keyboard_type,
    check_fn=_check_pyautogui,
    emoji="⌨️",
)