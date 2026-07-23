"""键盘输入工具 — 模拟键盘输入文本。

模块导入时通过 ``registry.register()`` 注册。

两种模式：
- **前台模式**（不传 hwnd）：ASCII 文本用 ``pyautogui.write()``，
  非 ASCII 文本（如中文）用 ``SendInput`` + ``KEYEVENTF_UNICODE``
  直接以 Unicode 码点注入键盘事件。需要目标窗口在前台且输入框已聚焦。
- **后台模式**（传 hwnd）：尝试通过 ``GetGUIThreadInfo`` 找到目标窗口中
  当前聚焦的子控件，找到则向其 ``PostMessage`` ``WM_CHAR``；
  找不到则向传入的 hwnd 发送。顶层窗口通常不直接处理键盘字符消息，
  如需指定具体子控件，先用 ``window_enum_child`` 枚举子窗口获取子控件 HWND，
  再直接传给本工具的 ``hwnd`` 参数。

不使用剪贴板。

依赖 ``pyautogui``（仅前台 ASCII 路径需要）。通过 ``check_fn`` 检测可用性。
"""

from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes
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
# Win32 常量
# ---------------------------------------------------------------------------

_WM_CHAR: int = 0x0102

# SendInput 相关
_INPUT_KEYBOARD: int = 1
_KEYEVENTF_UNICODE: int = 0x0004
_KEYEVENTF_KEYUP: int = 0x0002


# ---------------------------------------------------------------------------
# ctypes 结构体 — SendInput INPUT（必须与 Windows SDK 完全一致）
# ---------------------------------------------------------------------------
# sizeof(INPUT) 必须等于 Windows 期望值：
#   64-bit: 40 字节 (4 + 4pad + 32 union)
#   32-bit: 28 字节 (4 + 24 union)
# union 必须包含 MOUSEINPUT（最大的成员），否则 sizeof 偏小会导致
# SendInput 读到垃圾数据并产生不可预测的按键。


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("_input",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("_input", _INPUT_UNION),
    ]


# ---------------------------------------------------------------------------
# ctypes 结构体 — GetGUIThreadInfo（后台焦点窗口查找）
# ---------------------------------------------------------------------------


class _GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
        ("rcCursor", wintypes.RECT),
        ("rcClient", wintypes.RECT),
    ]


# ---------------------------------------------------------------------------
# Win32 函数 argtypes（一次性）
# ---------------------------------------------------------------------------
# 注意：不设置 SendInput 的 argtypes，否则 ctypes.byref / pointer
# 与 POINTER(_INPUT) 类型检查不匹配会抛 TypeError。

_user32 = ctypes.windll.user32

_user32.GetWindowThreadProcessId.argtypes = [
    wintypes.HWND,
    ctypes.POINTER(wintypes.DWORD),
]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD

_user32.GetGUIThreadInfo.argtypes = [
    wintypes.DWORD,
    ctypes.POINTER(_GUITHREADINFO),
]
_user32.GetGUIThreadInfo.restype = wintypes.BOOL

_user32.PostMessageW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
_user32.PostMessageW.restype = wintypes.BOOL

_user32.IsWindow.argtypes = [wintypes.HWND]
_user32.IsWindow.restype = wintypes.BOOL


# ---------------------------------------------------------------------------
# 前台 Unicode 输入（SendInput）
# ---------------------------------------------------------------------------


def _send_unicode_char(char: str) -> None:
    """通过 SendInput 发送单个 Unicode 字符。

    使用 KEYEVENTF_UNICODE 标志，直接以 Unicode 码点注入键盘事件。
    不经过剪贴板、不依赖输入法。仅支持 BMP 字符 (U+0000 ~ U+FFFF)。
    """
    code_point = ord(char)
    if code_point > 0xFFFF:
        logger.warning("Character U+%X exceeds BMP, skipping", code_point)
        return

    inputs = (_INPUT * 2)()

    # key down
    inputs[0].type = _INPUT_KEYBOARD
    inputs[0].ki.wVk = 0
    inputs[0].ki.wScan = code_point
    inputs[0].ki.dwFlags = _KEYEVENTF_UNICODE

    # key up
    inputs[1].type = _INPUT_KEYBOARD
    inputs[1].ki.wVk = 0
    inputs[1].ki.wScan = code_point
    inputs[1].ki.dwFlags = _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP

    # 不设 argtypes，用 ctypes.pointer 传数组指针
    sent = _user32.SendInput(2, ctypes.pointer(inputs), ctypes.sizeof(_INPUT))
    if sent == 0:
        err = ctypes.get_last_error()
        raise OSError(f"SendInput failed (error={err})")


def _send_unicode_text(text: str, interval: float) -> None:
    """逐字符通过 SendInput 发送 Unicode 文本。"""
    for char in text:
        _send_unicode_char(char)
        if interval > 0:
            time.sleep(interval)


# ---------------------------------------------------------------------------
# 后台目标窗口查找
# ---------------------------------------------------------------------------


def _get_focus_hwnd(hwnd: int) -> int:
    """尝试通过 GetGUIThreadInfo 找到目标窗口中当前聚焦的子控件。

    顶层窗口通常不直接处理 ``WM_CHAR``，真正处理字符输入的是
    其内部的 Edit / RichEdit / WebView 等子控件。

    如果 GetGUIThreadInfo 返回了焦点子控件，返回它；
    否则返回原始 hwnd（调用方应考虑用 window_enum_child 自行查找子窗口）。
    """
    thread_id = _user32.GetWindowThreadProcessId(hwnd, None)
    if thread_id:
        info = _GUITHREADINFO()
        info.cbSize = ctypes.sizeof(_GUITHREADINFO)
        if _user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)):
            if info.hwndFocus:
                return int(info.hwndFocus)

    return hwnd


def _post_chars(hwnd: int, text: str, interval: float) -> None:
    """通过 PostMessage 逐字符发送 WM_CHAR。

    wParam 为字符的 Unicode 码点，覆盖 ASCII 和 CJK。
    """
    for char in text:
        _user32.PostMessageW(hwnd, _WM_CHAR, ord(char), 0)
        if interval > 0:
            time.sleep(interval)


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _has_non_ascii(text: str) -> bool:
    """文本中是否包含非 ASCII 字符（如中文、日文等）。"""
    return any(ord(c) > 127 for c in text)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def _handle_keyboard_type(args: dict[str, Any]) -> dict:
    """模拟键盘输入文本。

    - 前台 ASCII：pyautogui.write()
    - 前台非 ASCII：SendInput + KEYEVENTF_UNICODE
    - 后台：GetGUIThreadInfo 找焦点子控件 → 找不到则用原始 hwnd → PostMessage WM_CHAR
    """
    text: str = str(args.get("text", ""))
    interval: float = float(args.get("interval", 0.0))
    hwnd: int = int(args.get("hwnd", 0))

    if not text:
        return tool_error("text is required and must be non-empty")

    # ---- 后台文本输入模式 ----
    if hwnd > 0:
        if not _user32.IsWindow(hwnd):
            return tool_error(f"Invalid window handle: hwnd={hwnd}", hwnd=hwnd)

        focus_hwnd = _get_focus_hwnd(hwnd)
        used_hwnd = focus_hwnd if focus_hwnd != hwnd else hwnd

        try:
            _post_chars(used_hwnd, text, interval)
        except Exception as exc:
            return tool_error(
                f"Background keyboard input failed: {exc}",
                text=text[:100], hwnd=hwnd, used_hwnd=used_hwnd,
            )

        logger.info(
            "keyboard_type | hwnd=%d used_hwnd=%d length=%d interval=%.2f (background)",
            hwnd, used_hwnd, len(text), interval,
        )

        return tool_result(
            success=True,
            text=text,
            length=len(text),
            interval=interval,
            hwnd=hwnd,
            used_hwnd=used_hwnd,
            mode="background",
        )

    # ---- 前台文本输入模式 ----

    if _has_non_ascii(text):
        # 非 ASCII（如中文）：SendInput + KEYEVENTF_UNICODE
        try:
            _send_unicode_text(text, interval)
        except Exception as exc:
            return tool_error(f"Foreground Unicode input failed: {exc}", text=text[:100])

        logger.info(
            "keyboard_type | length=%d interval=%.2f (foreground/unicode)",
            len(text), interval,
        )

        return tool_result(
            success=True,
            text=text,
            length=len(text),
            interval=interval,
            mode="foreground",
        )

    # ASCII 文本：pyautogui.write
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
        # 模拟键盘输入文本，支持前台和后台两种模式。
        # 前置条件：前台模式需 pyautogui 且输入框已聚焦；后台模式需先用 window_find 获取 HWND。
        # 调用效果：前台 ASCII 用 pyautogui.write；前台非 ASCII 用 SendInput+KEYEVENTF_UNICODE；
        #   后台尝试 GetGUIThreadInfo 找焦点子控件，找不到则用传入的 hwnd，再 PostMessage WM_CHAR。
        # 返回值：text、length、interval、mode（foreground 或 background）；后台额外返回 used_hwnd。
        # 典型场景：后台模式用于被遮挡窗口的文本输入；前台模式用于前台窗口。
        # 副作用：前台模式直接控制键盘；后台模式不需要前台焦点。两者都不碰剪贴板。
        "description": """Type text via simulated keyboard input.

## Prerequisites
- `pyautogui` must be installed (foreground ASCII only).
- The target input field must be focused (use `mouse_click` to click into it first).
- For background mode: use `window_find` first to obtain the HWND.

## Two Modes

### Foreground mode (no `hwnd`)
- **ASCII text**: Uses `pyautogui.write()` — simulates real keystrokes.
- **Non-ASCII text (CJK, etc.)**: Uses `SendInput` with `KEYEVENTF_UNICODE` to inject Unicode characters directly into the keyboard input stream. No clipboard, no IME. Only BMP characters (U+0000 ~ U+FFFF) are supported.

### Background mode (`hwnd` provided)
Attempts to find the focused child control via `GetGUIThreadInfo` — if the target window's thread has a focused child (e.g. an `Edit` control), `WM_CHAR` messages are sent to that child. If no focused child is found, messages are sent to the provided `hwnd` directly.

**Important**: The top-level window usually does not process `WM_CHAR` — only its child controls do. If background typing fails, use `window_enum_child` to enumerate the window's children, identify the correct input control (e.g. class_name `Edit`), and pass that child's HWND directly as the `hwnd` parameter.

The window can be obscured or in the background — no foreground focus needed.

## Returns
```json
{"success": true, "text": "hello world", "length": 11, "interval": 0.0, "mode": "foreground"}
// or with hwnd:
{"success": true, "text": "你好", "length": 2, "interval": 0.0, "hwnd": 12345, "used_hwnd": 67890, "mode": "background"}
```

## When to Use
- **Background mode**: After `window_find` → `mouse_click` (background) to focus an input field, then type text without stealing foreground focus. If typing fails, use `window_enum_child` to find the correct child control HWND and pass it directly.
- **Foreground mode**: After clicking into an input field with `mouse_click`. To fill in forms, search boxes, or text areas. To enter commands in a terminal or console.

## Side Effects / Notes
- Foreground mode directly controls the keyboard — will type into whatever field currently has focus. `pyautogui.FAILSAFE` is disabled.
- Background mode does not require foreground focus — messages are sent via `PostMessage`.
- **No clipboard involvement** — no mode touches the system clipboard.
- Foreground non-ASCII text uses `SendInput` + `KEYEVENTF_UNICODE`. Only BMP characters (U+0000 ~ U+FFFF) are supported; characters outside BMP (some emoji) are skipped with a warning.
- `interval` controls the delay between each keystroke (seconds). 0 = instant.
- **If background typing fails**: the top-level window likely doesn't process `WM_CHAR`. Use `window_enum_child` to find the child control (e.g. `Edit`) and pass its HWND as `hwnd`.
- Some applications (DirectX games, certain Electron apps) may not respond to `PostMessage` at all. Use foreground mode for those.""",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    # 要输入的文本，支持 Unicode 字符（包括中文）。
                    "description": "The text to type. Supports Unicode characters including CJK.",
                },
                "interval": {
                    "type": "number",
                    # 每次按键之间的延迟（秒），0 为即时，默认 0.0。
                    "description": "Delay between each keystroke in seconds. 0 = instant. Default: 0.0.",
                    "default": 0.0,
                },
                "hwnd": {
                    "type": "integer",
                    # 窗口句柄（HWND）。传入时使用后台文本输入模式，省略时使用前台模式。后台模式下如找不到焦点子控件，可用 window_enum_child 获取子控件 HWND 后直接传入。
                    "description": "Window handle (HWND). Can be a top-level window (from `window_find`) or a child control (from `window_enum_child`). When provided, uses background typing mode (PostMessage WM_CHAR). When omitted, uses foreground mode (pyautogui for ASCII, SendInput for non-ASCII).",
                },
            },
            "required": ["text"],
        },
    },
    handler=_handle_keyboard_type,
    check_fn=_check_pyautogui,
    emoji="⌨️",
)