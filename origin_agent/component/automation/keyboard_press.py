"""按键工具 — 模拟按键（如 Enter、Esc、Tab）及组合键。

模块导入时通过 ``registry.register()`` 注册。

两种模式：
- **前台模式**（不传 hwnd）：使用 ``pyautogui`` 模拟按键，需要目标窗口在前台。
- **后台模式**（传 hwnd）：使用 ``PostMessage`` 向指定窗口发送 ``WM_KEYDOWN`` /
  ``WM_KEYUP`` 消息，窗口可被遮挡，无需在前台。键名通过内部 VK 映射表解析。

依赖 ``pyautogui``（仅前台模式需要）。通过 ``check_fn`` 检测可用性。
当 key 包含 "+" 时自动拆分为组合键。
"""

from __future__ import annotations

import ctypes
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
# Win32 API 常量（后台按键模式）
# ---------------------------------------------------------------------------

_WM_KEYDOWN: int = 0x0100
_WM_KEYUP: int = 0x0101

_VK_MAP: dict[str, int] = {
    # 编辑/控制键
    "enter": 0x0D, "return": 0x0D,
    "escape": 0x1B, "esc": 0x1B,
    "tab": 0x09,
    "backspace": 0x08, "back": 0x08,
    "delete": 0x2E, "del": 0x2E,
    "insert": 0x2D,
    "space": 0x20,
    # 修饰键
    "ctrl": 0x11, "control": 0x11,
    "ctrlleft": 0xA2, "ctrlright": 0xA3,
    "alt": 0x12, "altleft": 0xA4, "altright": 0xA5,
    "shift": 0x10, "shiftleft": 0xA0, "shiftright": 0xA1,
    "win": 0x5B, "winleft": 0x5B, "winright": 0x5C,
    "leftwin": 0x5B, "rightwin": 0x5C,
    # 方向键
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    # 导航键
    "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pgup": 0x21,
    "pagedown": 0x22, "pgdn": 0x22,
    # 功能键
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
    "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
    "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "f13": 0x7C, "f14": 0x7D, "f15": 0x7E, "f16": 0x7F,
    "f17": 0x80, "f18": 0x81, "f19": 0x82, "f20": 0x83,
    "f21": 0x84, "f22": 0x85, "f23": 0x86, "f24": 0x87,
    # 锁定键
    "capslock": 0x14,
    "numlock": 0x90,
    "scrolllock": 0x91,
    # 其他
    "printscreen": 0x2C, "prtsc": 0x2C,
    "pause": 0x13,
    "contextmenu": 0x5D, "apps": 0x5D,
    "clear": 0x0C,
    # 小键盘
    "numpad0": 0x60, "numpad1": 0x61, "numpad2": 0x62,
    "numpad3": 0x63, "numpad4": 0x64, "numpad5": 0x65,
    "numpad6": 0x66, "numpad7": 0x67, "numpad8": 0x68,
    "numpad9": 0x69,
    "multiply": 0x6A, "add": 0x6B, "subtract": 0x6D,
    "decimal": 0x6E, "divide": 0x6F,
}


def _resolve_vk(key: str) -> int | None:
    """将键名解析为 Windows VK 码。"""
    key_lower = key.lower().strip()
    if key_lower in _VK_MAP:
        return _VK_MAP[key_lower]
    if len(key_lower) == 1:
        ch = key_lower.upper()
        if 'A' <= ch <= 'Z':
            return ord(ch)
        if '0' <= ch <= '9':
            return ord(ch)
    return None


def _post_key_press(hwnd: int, vk_codes: list[int], presses: int) -> bool:
    """通过 PostMessage 向窗口发送按键消息（后台按键）。

    单键：WM_KEYDOWN → WM_KEYUP。
    组合键：依次按下所有键，再逆序释放。
    """
    user32 = ctypes.windll.user32
    for _ in range(presses):
        for vk in vk_codes:
            user32.PostMessageW(hwnd, _WM_KEYDOWN, vk, 0)
        for vk in reversed(vk_codes):
            user32.PostMessageW(hwnd, _WM_KEYUP, vk, 0)
    return True


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def _handle_keyboard_press(args: dict[str, Any]) -> dict:
    """模拟按键或组合键（前台 pyautogui 或后台 PostMessage）。"""
    key: str = str(args.get("key", "")).strip()
    presses: int = int(args.get("presses", 1))
    hwnd: int = int(args.get("hwnd", 0))

    if not key:
        return tool_error("key is required")
    if presses < 1:
        return tool_error(f"presses must be >= 1, got {presses}", presses=presses)

    # ---- 后台按键模式 ----
    if hwnd > 0:
        if not ctypes.windll.user32.IsWindow(hwnd):
            return tool_error(f"Invalid window handle: hwnd={hwnd}", hwnd=hwnd)

        keys = [k.strip() for k in key.split("+") if k.strip()]
        if not keys:
            return tool_error(f"Invalid key combination: '{key}'")

        vk_codes: list[int] = []
        for k in keys:
            vk = _resolve_vk(k)
            if vk is None:
                return tool_error(
                    f"Cannot resolve key '{k}' to a VK code in background mode",
                    key=key, hwnd=hwnd,
                )
            vk_codes.append(vk)

        try:
            _post_key_press(hwnd, vk_codes, presses)
        except Exception as exc:
            return tool_error(
                f"Background key press failed: {exc}", key=key, hwnd=hwnd,
            )

        logger.info(
            "keyboard_press | hwnd=%d key='%s' presses=%d (background)",
            hwnd, key, presses,
        )

        return tool_result(
            success=True,
            key=key,
            presses=presses,
            hwnd=hwnd,
            mode="background",
        )

    # ---- 前台按键模式 ----
    import pyautogui

    pyautogui.FAILSAFE = False

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

    logger.info("keyboard_press | key='%s' presses=%d (foreground)", key, presses)

    return tool_result(
        success=True,
        key=key,
        presses=presses,
        mode="foreground",
    )


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

registry.register(
    name="keyboard_press",
    toolset="automation",
    schema={
        # 模拟按键或组合键，支持前台 pyautogui 和后台 PostMessage 两种模式。
        # 前置条件：前台模式需 pyautogui；后台模式需先用 window_find 获取 HWND。
        # 调用效果：前台模式用 pyautogui 按键；后台模式通过 PostMessage 发送 WM_KEYDOWN/UP。
        # 返回值：key、presses、mode（foreground 或 background）。
        # 典型场景：后台模式用于被遮挡窗口的按键；前台模式用于前台窗口。
        # 副作用：前台模式直接控制键盘；后台模式不需要前台焦点。
        "description": """Press a single key or a key combination.

## Prerequisites
- `pyautogui` must be installed (foreground mode only).
- Windows only.
- For background mode: use `window_find` first to obtain the HWND.

## Two Modes

### Foreground mode (no `hwnd`)
Uses `pyautogui` to simulate keystrokes. If `key` contains `+`, it is treated as a key combination and executed via `pyautogui.hotkey()` (e.g. "ctrl+c" presses Ctrl then C then releases both). Otherwise, `pyautogui.press()` is used for a single key. The target window must be in the foreground.

### Background mode (`hwnd` provided)
Uses `PostMessage` to send `WM_KEYDOWN` / `WM_KEYUP` messages directly to the target window. The window can be obscured or in the background — no foreground focus needed. Key names are resolved to Windows VK codes internally.

## Returns
```json
{"success": true, "key": "enter", "presses": 1, "mode": "foreground"}
// or with hwnd:
{"success": true, "key": "enter", "presses": 1, "hwnd": 12345, "mode": "background"}
```

## When to Use
- **Background mode**: Send keystrokes to a window without stealing focus. Use after `window_find` to obtain the HWND. Ideal for batch automation where disrupting the user's focus is undesirable.
- **Foreground mode**: Press Enter to confirm a dialog, Escape to close a popup, "ctrl+c" to copy, "alt+tab" to switch windows, "ctrl+s" to save.

## Side Effects / Notes
- Foreground mode directly controls the keyboard — `pyautogui.FAILSAFE` is disabled.
- Background mode does not require foreground focus — keystrokes are sent via `PostMessage`.
- Key names follow pyautogui conventions (e.g. "enter", "escape", "tab", "ctrl", "alt", "shift", "win", "space", "backspace", "delete").
- For combination keys, keys are pressed left-to-right and released in reverse order.
- In background mode, not all applications respond to `PostMessage` keyboard messages (e.g. DirectX games, some Electron apps). Use foreground mode for those.
- In background mode, only keys resolvable to VK codes are supported. Plain letter keys (a-z), digit keys (0-9), and all entries in the internal VK map are supported. Symbol keys (!, @, #, etc.) are NOT supported in background mode — use `keyboard_type` with `hwnd` instead.""",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    # 按键名称（如 enter、escape、tab）或用 + 分隔的组合键（如 ctrl+c、alt+tab、ctrl+shift+s）。
                    "description": "Key name (e.g. 'enter', 'escape', 'tab') or key combination with '+' separator (e.g. 'ctrl+c', 'alt+tab', 'ctrl+shift+s').",
                },
                "presses": {
                    "type": "integer",
                    # 按键次数，默认 1。
                    "description": "Number of times to press the key. Default: 1.",
                    "default": 1,
                },
                "hwnd": {
                    "type": "integer",
                    # 窗口句柄（HWND）。传入时使用后台按键模式（PostMessage），省略时使用前台模式（pyautogui）。
                    "description": "Window handle (HWND) from `window_find`. When provided, uses background key mode (PostMessage). When omitted, uses foreground mode (pyautogui).",
                },
            },
            "required": ["key"],
        },
    },
    handler=_handle_keyboard_press,
    check_fn=_check_pyautogui,
    emoji="🔑",
)