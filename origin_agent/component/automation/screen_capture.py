"""窗口截屏工具 — 通过 PrintWindow 后台截取指定窗口的屏幕内容。

模块导入时通过 ``registry.register()`` 注册。

仅兼容 Windows。使用 ``ctypes`` 调用 Win32 API 实现后台截屏
（窗口被遮挡时仍可截取），通过 PIL 保存图片到 agentspace。

复用 ``window_focus.py`` 中的 ``_find_window_by_title`` 定位窗口。
"""

from __future__ import annotations

import ctypes
import logging
import time
from typing import Any, Optional

from abstract.tools.registry import registry, tool_error, tool_result
from system.sandbox import SandboxError

logger = logging.getLogger(__name__)

# 尝试设置 DPI 感知，使 PrintWindow 获取正确尺寸
# 必须在首次调用 GDI 操作前设置
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
except (AttributeError, OSError):
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        logger.debug("Could not set DPI awareness — screenshots may be scaled")

# ---------------------------------------------------------------------------
# Win32 API 常量
# ---------------------------------------------------------------------------

_PW_RENDERFULLCONTENT: int = 3  # PrintWindow flag — 渲染完整内容（含 DX/HW 加速）
_SRCCOPY: int = 0x00CC0020  # BitBlt raster operation

# ---------------------------------------------------------------------------
# Win32 结构体
# ---------------------------------------------------------------------------


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", _BITMAPINFOHEADER),
        ("bmiColors", ctypes.c_uint32 * 3),
    ]


# ---------------------------------------------------------------------------
# 沙箱引用（与 shell.py 相同的延迟引用模式）
# ---------------------------------------------------------------------------

from component.tools.filesystem import _s as _get_sandbox  # noqa: E402


def _s():
    return _get_sandbox()


# ---------------------------------------------------------------------------
# Win32 截屏核心
# ---------------------------------------------------------------------------


def _capture_window(hwnd: int) -> Any:
    """通过 PrintWindow 后台截取窗口内容，返回 PIL Image 或 None。

    使用 PrintWindow(PW_RENDERFULLCONTENT) 获取后台渲染内容。
    如果 PrintWindow 失败，fallback 到 BitBlt 方案。
    """
    try:
        from PIL import Image as PILImage
    except ImportError:
        logger.error("PIL not available — cannot capture window")
        return None

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    # 获取窗口客户区尺寸
    rect = _RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    width: int = rect.right - rect.left
    height: int = rect.bottom - rect.top

    if width <= 0 or height <= 0:
        logger.warning("window_capture | invalid window size %dx%d for hwnd=%d", width, height, hwnd)
        return None

    # 创建兼容 DC 和 Bitmap
    hwnd_dc = user32.GetDC(hwnd)
    mfc_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
    gdi32.SelectObject(mfc_dc, bitmap)

    try:
        # 尝试 PrintWindow（后台截屏）
        result = user32.PrintWindow(hwnd, mfc_dc, _PW_RENDERFULLCONTENT)

        if result != 1:
            # PrintWindow 失败 — fallback 到 BitBlt
            logger.debug("window_capture | PrintWindow failed (result=%d), falling back to BitBlt", result)
            success = gdi32.BitBlt(mfc_dc, 0, 0, width, height, hwnd_dc, 0, 0, _SRCCOPY)
            if not success:
                logger.error("window_capture | BitBlt also failed for hwnd=%d", hwnd)
                return None

        # 从 DIB 段提取像素数据 — 必须在 DeleteObject 之前完成
        bmi = _BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = height  # 正值 = bottom-up 位图
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0  # BI_RGB

        pixel_buffer = (ctypes.c_ubyte * (width * height * 4))()
        gdi32.GetDIBits(mfc_dc, bitmap, 0, height, pixel_buffer, ctypes.byref(bmi), 0)

        # 构造 PIL Image — BGRA → RGBA → RGB
        img = PILImage.frombuffer("RGBA", (width, height), bytes(pixel_buffer), "raw", "BGRA", 0, 1)
        img = img.convert("RGB")

    finally:
        # 清理 GDI 资源（GetDIBits 已完成，安全释放）
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mfc_dc)
        user32.ReleaseDC(hwnd, hwnd_dc)

    return img


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def _handle_screen_capture(args: dict[str, Any]) -> dict:
    """通过窗口标题截取窗口内容并保存到 agentspace。"""
    from .window_focus import _find_window_by_title

    window_title: str = str(args.get("window_title", "")).strip()
    save_path: str = str(args.get("save_path", "")).strip()

    if not window_title:
        return tool_error("window_title is required")

    hwnd: Optional[int] = _find_window_by_title(window_title)
    if hwnd is None:
        return tool_error(
            f"No window found with title containing '{window_title}'",
            window_title=window_title,
        )

    # 截取窗口
    img = _capture_window(hwnd)
    if img is None:
        return tool_error(
            f"Failed to capture window content (hwnd={hwnd})",
            window_title=window_title,
        )

    width, height = img.width, img.height

    # 生成默认保存路径
    if not save_path:
        timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        save_path = f"ws:uploads/screenshot_{timestamp}.png"

    # 通过沙箱解析路径并保存
    try:
        resolved = _s().resolve_write(save_path)
        resolved.real.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(resolved.real), format="PNG")
    except SandboxError as exc:
        return tool_error(str(exc), window_title=window_title, save_path=save_path)
    except Exception as exc:
        return tool_error(f"Failed to save screenshot: {exc}", window_title=window_title)

    logger.info("screen_capture | title='%s' hwnd=%d → %s (%dx%d)",
                window_title, hwnd, save_path, width, height)

    return tool_result(
        success=True,
        window_title=window_title,
        hwnd=hwnd,
        path=save_path,
        width=width,
        height=height,
    )


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

registry.register(
    name="screen_capture",
    toolset="automation",
    schema={
        "description": """Capture a screenshot of a specific window (even if obscured) and save it to agentspace.

## Prerequisites
- Windows only.
- The target window must exist and be visible.
- Pillow (PIL) must be installed.

## Effect
Locates the window by partial title match (case-insensitive), then uses `PrintWindow` with `PW_RENDERFULLCONTENT` to capture its content — even when the window is behind other windows. The screenshot is saved as a PNG file to agentspace.

## Returns
```json
{"success": true, "window_title": "...", "hwnd": 12345, "path": "ws:uploads/screenshot_20260101_120000.png", "width": 1920, "height": 1080}
```
The `path` is a sandbox logical path (ws: namespace). Use it with `template_match` or `read_image` to process the screenshot.

## When to Use
- Before running `template_match` to locate UI elements on screen.
- To inspect the current state of an application window.
- As the first step in an automation flow: capture → match → click.

## Side Effects / Notes
- Creates a PNG file in agentspace (default: `ws:uploads/screenshot_{timestamp}.png`).
- Does NOT return image content (base64) — only metadata and path.
- Uses `PrintWindow` for background capture; falls back to `BitBlt` if PrintWindow fails.
- DirectX/hardware-accelerated windows may produce blank screenshots in rare cases.
- DPI awareness is set to per-monitor for accurate coordinates.""",
        "parameters": {
            "type": "object",
            "properties": {
                "window_title": {
                    "type": "string",
                    "description": "Partial window title to search for (case-insensitive). The first matching visible window will be captured.",
                },
                "save_path": {
                    "type": "string",
                    "description": "Sandbox path to save the screenshot (e.g. 'ws:uploads/my_screenshot.png'). If omitted, defaults to 'ws:uploads/screenshot_{timestamp}.png'.",
                },
            },
            "required": ["window_title"],
        },
    },
    handler=_handle_screen_capture,
    emoji="📸",
)