"""Windows GUI 操控工具 — 截图、鼠标、键盘、窗口管理。

依赖 pyautogui + pygetwindow + Pillow。
模块导入时通过 ``registry.register()`` 注册全部工具。
"""

from __future__ import annotations

import base64
import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from PIL import Image

from abstract.tools.registry import registry, tool_error, tool_result
from entity.constant import LOG_PREVIEW_CHARS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 延迟导入 — 避免启动时强制要求 GUI 依赖
# ---------------------------------------------------------------------------

def _get_sandbox():
    """延迟获取 sandbox 引用。"""
    from component.tools.filesystem import _s
    return _s()


def _resolve_ws_dir(subdir: str = "screenshots") -> Path:
    """解析 ws: 下用于存放截图/导出文件的目录，自动创建。"""
    sb = _get_sandbox()
    r = sb.resolve_write(f"ws:{subdir}/.placeholder")
    d = r.real.parent
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# 辅助：截图保存与编码
# ---------------------------------------------------------------------------

def _save_screenshot(img: Image.Image, filename: str | None = None) -> tuple[str, str, int]:
    """将 PIL Image 保存到 ws:screenshots/ 下，返回 (ws_path, b64, size_bytes)。"""
    
    if filename is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"screenshot_{ts}.png"
    out_dir = _resolve_ws_dir("screenshots")
    out_path = out_dir / filename
    img.save(str(out_path), format="PNG")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    return f"ws:screenshots/{filename}", b64, out_path.stat().st_size


# ---------------------------------------------------------------------------
# 1. gui_screenshot
# ---------------------------------------------------------------------------

def _handle_gui_screenshot(args: dict[str, Any]) -> dict:
    try:
        import pyautogui as _pyautogui
    except ImportError:
        raise ImportError(
            "pyautogui is not installed. Run: pip install pyautogui"
        )

    region = args.get("region")  # [x, y, w, h] or None
    filename: str = str(args.get("filename", "")).strip()

    if region is not None:
        if not (isinstance(region, list) and len(region) == 4):
            return tool_error("region must be a list in [x, y, width, height] format")
        x, y, w, h = int(region[0]), int(region[1]), int(region[2]), int(region[3])
        img = _pyautogui.screenshot(region=(x, y, w, h))
    else:
        img = _pyautogui.screenshot()

    ws_path, b64, size_bytes = _save_screenshot(img, filename)

    return tool_result(
        path=ws_path,
        size=size_bytes,
        width=img.width,
        height=img.height,
        base64_preview=b64[:LOG_PREVIEW_CHARS] + "..." if len(b64) > LOG_PREVIEW_CHARS else b64,
        message=f"Screenshot saved: {ws_path} ({img.width}x{img.height}, {size_bytes/1024:.1f} KB)",
    )


# ---------------------------------------------------------------------------
# 2. gui_mouse_move
# ---------------------------------------------------------------------------

def _handle_gui_mouse_move(args: dict[str, Any]) -> dict:
    try:
        import pyautogui as _pyautogui
    except ImportError:
        raise ImportError(
            "pyautogui is not installed. Run: pip install pyautogui"
        )

    x: int = int(args["x"])
    y: int = int(args["y"])
    duration: float = float(args.get("duration", 0.3))

    _pyautogui.moveTo(x, y, duration=duration)
    actual = _pyautogui.position()

    return tool_result(
        target={"x": x, "y": y},
        actual={"x": actual.x, "y": actual.y},
        message=f"Mouse moved to ({actual.x}, {actual.y})",
    )


# ---------------------------------------------------------------------------
# 3. gui_mouse_click
# ---------------------------------------------------------------------------

def _handle_gui_mouse_click(args: dict[str, Any]) -> dict:
    try:
        import pyautogui as _pyautogui
    except ImportError:
        raise ImportError(
            "pyautogui is not installed. Run: pip install pyautogui"
        )

    x = args.get("x")
    y = args.get("y")
    button: str = str(args.get("button", "left")).lower()
    clicks: int = int(args.get("clicks", 1))
    interval: float = float(args.get("interval", 0.0))
    duration: float = float(args.get("duration", 0.0))

    if button not in ("left", "right", "middle"):
        return tool_error(f"Invalid button type: {button} (supported: left/right/middle)")
    if clicks < 1 or clicks > 3:
        return tool_error(f"Invalid click count: {clicks} (supported: 1-3)")

    if x is not None and y is not None:
        _pyautogui.click(int(x), int(y), clicks=clicks, interval=interval,
                         button=button, duration=duration)
        pos_msg = f"({int(x)}, {int(y)})"
    else:
        _pyautogui.click(clicks=clicks, interval=interval, button=button,
                         duration=duration)
        pos = _pyautogui.position()
        pos_msg = f"({pos.x}, {pos.y})"

    return tool_result(
        position=pos_msg,
        button=button,
        clicks=clicks,
        message=f"{button}-click at {pos_msg}, {clicks} time(s)",
    )


# ---------------------------------------------------------------------------
# 4. gui_mouse_drag
# ---------------------------------------------------------------------------

def _handle_gui_mouse_drag(args: dict[str, Any]) -> dict:
    try:
        import pyautogui as _pyautogui
    except ImportError:
        raise ImportError(
            "pyautogui is not installed. Run: pip install pyautogui"
        )

    start_x: int = int(args.get("start_x", args.get("x", 0)))
    start_y: int = int(args.get("start_y", args.get("y", 0)))
    end_x: int = int(args["end_x"])
    end_y: int = int(args["end_y"])
    button: str = str(args.get("button", "left")).lower()
    duration: float = float(args.get("duration", 0.5))

    if button not in ("left", "right", "middle"):
        return tool_error(f"Invalid button type: {button}")

    _pyautogui.moveTo(start_x, start_y, duration=0.1)
    _pyautogui.drag(end_x - start_x, end_y - start_y,
                    duration=duration, button=button)

    return tool_result(
        start={"x": start_x, "y": start_y},
        end={"x": end_x, "y": end_y},
        message=f"Dragged from ({start_x}, {start_y}) to ({end_x}, {end_y})",
    )


# ---------------------------------------------------------------------------
# 5. gui_mouse_scroll
# ---------------------------------------------------------------------------

def _handle_gui_mouse_scroll(args: dict[str, Any]) -> dict:
    try:
        import pyautogui as _pyautogui
    except ImportError:
        raise ImportError(
            "pyautogui is not installed. Run: pip install pyautogui"
        )

    clicks: int = int(args.get("clicks", 3))
    x = args.get("x")
    y = args.get("y")

    if x is not None and y is not None:
        _pyautogui.scroll(clicks, int(x), int(y))
    else:
        _pyautogui.scroll(clicks)

    direction = "up" if clicks > 0 else "down"
    return tool_result(
        direction=direction,
        amount=abs(clicks),
        message=f"Scrolled {abs(clicks)} notch(es) {direction}",
    )


# ---------------------------------------------------------------------------
# 6. gui_type
# ---------------------------------------------------------------------------

def _handle_gui_type(args: dict[str, Any]) -> dict:
    try:
        import pyautogui as _pyautogui
    except ImportError:
        raise ImportError(
            "pyautogui is not installed. Run: pip install pyautogui"
        )

    text: str = str(args["text"])
    interval: float = float(args.get("interval", 0.0))

    _pyautogui.typewrite(text, interval=interval)

    return tool_result(
        length=len(text),
        message=f"Typed {len(text)} character(s)",
    )


# ---------------------------------------------------------------------------
# 7. gui_press_keys
# ---------------------------------------------------------------------------

def _handle_gui_press_keys(args: dict[str, Any]) -> dict:
    try:
        import pyautogui as _pyautogui
    except ImportError:
        raise ImportError(
            "pyautogui is not installed. Run: pip install pyautogui"
        )

    keys = args.get("keys", [])

    if isinstance(keys, str):
        keys = [keys]
    if not isinstance(keys, list) or len(keys) == 0:
        return tool_error("keys must be a non-empty list, e.g. [\"ctrl\", \"c\"]")

    keys = [str(k) for k in keys]

    if len(keys) == 1:
        _pyautogui.press(keys[0])
        return tool_result(
            keys=keys,
            message=f"Pressed: {keys[0]}",
        )
    else:
        _pyautogui.hotkey(*keys)
        return tool_result(
            keys=keys,
            combination="+".join(keys),
            message=f"Pressed combo: {'+'.join(keys)}",
        )


# ---------------------------------------------------------------------------
# 8. gui_get_mouse_position
# ---------------------------------------------------------------------------

def _handle_gui_get_mouse_position(_args: dict[str, Any]) -> dict:
    try:
        import pyautogui as _pyautogui
    except ImportError:
        raise ImportError(
            "pyautogui is not installed. Run: pip install pyautogui"
        )

    pos = _pyautogui.position()

    return tool_result(
        x=pos.x,
        y=pos.y,
        message=f"Mouse position: ({pos.x}, {pos.y})",
    )


# ---------------------------------------------------------------------------
# 9. gui_get_screen_size
# ---------------------------------------------------------------------------

def _handle_gui_get_screen_size(_args: dict[str, Any]) -> dict:
    try:
        import pyautogui as _pyautogui
    except ImportError:
        raise ImportError(
            "pyautogui is not installed. Run: pip install pyautogui"
        )

    w, h = _pyautogui.size()

    return tool_result(
        width=w,
        height=h,
        message=f"Screen resolution: {w} x {h}",
    )


# ---------------------------------------------------------------------------
# 10. gui_get_windows
# ---------------------------------------------------------------------------

def _handle_gui_get_windows(args: dict[str, Any]) -> dict:
    try:
        import pyautogui as _pyautogui
    except ImportError:
        raise ImportError(
            "pyautogui is not installed. Run: pip install pyautogui"
        )
    try:
        import pygetwindow as _pygetwindow
    except ImportError:
        raise ImportError(
            "pygetwindow is not installed. Run: pip install pygetwindow"
        )

    title_filter: str = str(args.get("title", "")).strip().lower()
    max_results: int = int(args.get("max_results", 50))

    all_windows = _pygetwindow.getAllWindows()
    results = []

    for w in all_windows:
        if not w.title.strip():
            continue
        if title_filter and title_filter not in w.title.lower():
            continue
        results.append({
            "title": w.title,
            "left": w.left,
            "top": w.top,
            "width": w.width,
            "height": w.height,
            "visible": getattr(w, "visible", None),
        })
        if len(results) >= max_results:
            break

    return tool_result(
        count=len(results),
        windows=results,
        filter=title_filter or None,
        message=f"Found {len(results)} matching window(s)",
    )


# ---------------------------------------------------------------------------
# 11. gui_focus_window
# ---------------------------------------------------------------------------

def _handle_gui_focus_window(args: dict[str, Any]) -> dict:
    try:
        import pyautogui as _pyautogui
    except ImportError:
        raise ImportError(
            "pyautogui is not installed. Run: pip install pyautogui"
        )
    try:
        import pygetwindow as _pygetwindow
    except ImportError:
        raise ImportError(
            "pygetwindow is not installed. Run: pip install pygetwindow"
        )

    title: str = str(args["title"]).strip()
    bring_to_front: bool = bool(args.get("bring_to_front", True))

    if not title:
        return tool_error("title is required")

    matches = _pygetwindow.getWindowsWithTitle(title)
    if not matches:
        return tool_error(
            f"未找到包含 \"{title}\" 的窗口",
            suggestion="用 gui_get_windows 列出所有窗口",
        )

    win = matches[0]
    try:
        if bring_to_front:
            win.activate()
        else:
            win.focus()
    except Exception:
        # pygetwindow 的窗口 focus 在部分环境可能不可用
        try:
            win.minimize()
            win.restore()
        except Exception:
            return tool_error(
                f"无法聚焦窗口 \"{win.title}\"，请手动切换到该窗口",
                title=win.title,
            )

    return tool_result(
        title=win.title,
        position={"left": win.left, "top": win.top},
        size={"width": win.width, "height": win.height},
        message=f"Focused window: {win.title}",
    )


# ---------------------------------------------------------------------------
# 12. gui_get_active_window
# ---------------------------------------------------------------------------

def _handle_gui_get_active_window(_args: dict[str, Any]) -> dict:
    try:
        import pyautogui as _pyautogui
    except ImportError:
        raise ImportError(
            "pyautogui is not installed. Run: pip install pyautogui"
        )
    try:
        import pygetwindow as _pygetwindow
    except ImportError:
        raise ImportError(
            "pygetwindow is not installed. Run: pip install pygetwindow"
        )

    try:
        win = _pygetwindow.getActiveWindow()
    except Exception:
        return tool_error("Unable to get active window info")

    if win is None:
        return tool_error("Unable to get active window (may not have a GUI environment)")

    return tool_result(
        title=win.title,
        left=win.left,
        top=win.top,
        width=win.width,
        height=win.height,
        message=f"Active window: {win.title} ({win.width}x{win.height})",
    )


# ---------------------------------------------------------------------------
# 13. gui_locate_on_screen
# ---------------------------------------------------------------------------

def _handle_gui_locate_on_screen(args: dict[str, Any]) -> dict:
    try:
        import pyautogui as _pyautogui
    except ImportError:
        raise ImportError(
            "pyautogui is not installed. Run: pip install pyautogui"
        )

    image_path: str = str(args["image_path"]).strip()
    confidence: float = float(args.get("confidence", 0.9))

    if not image_path:
        return tool_error("image_path is required — template image path to search for")

    # 支持 ws: 路径
    if image_path.startswith("ws:"):
        sb = _get_sandbox()
        try:
            r = sb.resolve_read(image_path)
            image_path = str(r.real)
        except Exception as e:
            return tool_error(f"Unable to resolve path {image_path}: {e}")

    if not Path(image_path).exists():
        return tool_error(f"Template image not found: {image_path}")

    try:
        location = _pyautogui.locateOnScreen(image_path, confidence=confidence)
    except Exception as e:
        return tool_error(f"Screen search failed: {e}")

    if location is None:
        return tool_result(
            found=False,
            message=f"Image not found on screen (confidence={confidence})",
        )

    center = _pyautogui.center(location)

    return tool_result(
        found=True,
        location={"left": location.left, "top": location.top,
                  "width": location.width, "height": location.height},
        center={"x": center.x, "y": center.y},
        message=f"Match found, center: ({center.x}, {center.y})",
    )


# ===========================================================================
# Registration — 13 个工具
# ===========================================================================

_COORD_PROPS: dict = {
    "x": {"type": "integer", "description": "X 坐标（像素）"},
    "y": {"type": "integer", "description": "Y 坐标（像素）"},
}

# 1
registry.register(
    name="gui_screenshot",
    toolset="extools",
    schema={
        # 截取屏幕并保存到 ws:screenshots/。
        #
        # ## 前置条件
        # 必须安装 pyautogui 和 Pillow。
        # 当前环境需要有 GUI 桌面（无头服务器可能无法截图）。
        #
        # ## 调用效果
        # 截取全屏或指定区域 [x, y, width, height]，保存为 PNG 文件到 ws:screenshots/。
        # 返回 ws: 路径、文件大小、尺寸和 base64 预览。
        #
        # ## 返回
        # ```json
        # {"path": "ws:screenshots/screenshot_xxx.png", "size": 12345, "width": 1920, "height": 1080, "base64_preview": "...", "message": "Screenshot saved: ..."}
        # ```
        #
        # ## 何时使用
        # - 需要查看当前屏幕状态。
        # - 捕获 GUI 操作结果。
        # - 截取特定窗口或区域进行分析。
        #
        # ## 副作用/注意
        # - 生成图片文件并写入工作空间。
        # - 截取区域时坐标必须在屏幕范围内。
        # - 无 GUI 环境会失败。
        "description": """Take a screenshot and save it to ws:screenshots/.

## Prerequisites
pyautogui and Pillow must be installed. The current environment must have a GUI desktop (headless servers may fail).

## Effect
Captures the full screen or a specified region [x, y, width, height] and saves it as a PNG file under ws:screenshots/. Returns the ws: path, file size, dimensions, and a base64 preview.

## Returns
```json
{"path": "ws:screenshots/screenshot_xxx.png", "size": 12345, "width": 1920, "height": 1080, "base64_preview": "...", "message": "Screenshot saved: ..."}
```

## When to Use
- Inspect the current screen state.
- Capture the result of GUI operations.
- Screenshot a specific window or region for analysis.

## Side Effects / Notes
- Creates an image file and writes it to the workspace.
- Region coordinates must be within the screen bounds.
- Fails in environments without a GUI.""",
        "parameters": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 4,
                    "maxItems": 4,
                    # 截图区域 [x, y, width, height]，省略则截全屏。
                    "description": """Capture region [x, y, width, height], omit for fullscreen.""",
                },
                "filename": {
                    "type": "string",
                    # 自定义文件名（不含路径），默认自动生成时间戳名称。
                    "description": """Custom filename (without path). Auto-generates a timestamp name by default.""",
                },
            },
            "required": [],
        },
    },
    handler=_handle_gui_screenshot,
    emoji="📸",
)

# 2
registry.register(
    name="gui_mouse_move",
    toolset="extools",
    schema={
        # 移动鼠标到指定屏幕坐标。
        #
        # ## 前置条件
        # 必须安装 pyautogui。
        # 当前环境需要有 GUI 桌面。
        #
        # ## 调用效果
        # 将鼠标光标移动到 (x, y) 坐标。duration 控制移动动画时长。
        #
        # ## 返回
        # ```json
        # {"target": {"x": 100, "y": 200}, "actual": {"x": 100, "y": 200}, "message": "Mouse moved to (100, 200)"}
        # ```
        #
        # ## 何时使用
        # - 在点击前将鼠标移动到目标位置。
        # - 配合截图定位元素后移动鼠标。
        #
        # ## 副作用/注意
        # - 会改变当前鼠标光标位置。
        # - 坐标必须在屏幕范围内。
        "description": """Move the mouse to specified screen coordinates.

## Prerequisites
pyautogui must be installed. The current environment must have a GUI desktop.

## Effect
Moves the mouse cursor to the (x, y) coordinate. duration controls the animation time of the movement.

## Returns
```json
{"target": {"x": 100, "y": 200}, "actual": {"x": 100, "y": 200}, "message": "Mouse moved to (100, 200)"}
```

## When to Use
- Move the cursor to a target position before clicking.
- Move the mouse after locating an element in a screenshot.

## Side Effects / Notes
- Changes the current mouse cursor position.
- Coordinates must be within the screen bounds.""",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": """X coordinate in pixels."""},
                "y": {"type": "integer", "description": """Y coordinate in pixels."""},
                "duration": {
                    "type": "number",
                    # 移动耗时（秒），默认 0.3。
                    "description": """Movement duration in seconds (default 0.3).""",
                    "default": 0.3,
                },
            },
            "required": ["x", "y"],
        },
    },
    handler=_handle_gui_mouse_move,
    emoji="🖱️",
)

# 3
registry.register(
    name="gui_mouse_click",
    toolset="extools",
    schema={
        # 在指定坐标或当前鼠标位置点击。
        #
        # ## 前置条件
        # 必须安装 pyautogui。
        # 当前环境需要有 GUI 桌面。
        #
        # ## 调用效果
        # 在 (x, y) 或当前鼠标位置点击指定按键。支持单击、双击和三击，可设置点击间隔和移动耗时。
        #
        # ## 返回
        # ```json
        # {"position": "(100, 200)", "button": "left", "clicks": 1, "message": "left-click at (100, 200), 1 time(s)"}
        # ```
        #
        # ## 何时使用
        # - 点击按钮、链接、菜单等 UI 元素。
        # - 双击打开文件或选中文字。
        #
        # ## 副作用/注意
        # - 会实际移动鼠标并触发点击。
        # - 错误坐标可能点击到非预期位置。
        "description": """Click the mouse at specified coordinates or the current position.

## Prerequisites
pyautogui must be installed. The current environment must have a GUI desktop.

## Effect
Clicks the specified mouse button at (x, y) or the current cursor position. Supports single, double, and triple clicks, with configurable interval and movement duration.

## Returns
```json
{"position": "(100, 200)", "button": "left", "clicks": 1, "message": "left-click at (100, 200), 1 time(s)"}
```

## When to Use
- Click buttons, links, menus, or other UI elements.
- Double-click to open files or select text.

## Side Effects / Notes
- Physically moves the mouse and triggers clicks.
- Incorrect coordinates may click unintended targets.""",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": """X coordinate. Omit to click at the current position."""},
                "y": {"type": "integer", "description": """Y coordinate. Omit to click at the current position."""},
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    # 鼠标按键，默认 left。
                    "description": """Mouse button, default left.""",
                    "default": "left",
                },
                "clicks": {
                    "type": "integer",
                    # 点击次数，1=单击 2=双击，默认 1。
                    "description": """Click count. 1=single click, 2=double click, default 1.""",
                    "default": 1,
                },
                "interval": {
                    "type": "number",
                    # 多次点击间隔（秒），默认 0。
                    "description": """Interval between clicks in seconds (default 0).""",
                    "default": 0.0,
                },
                "duration": {
                    "type": "number",
                    # 移动到目标位置的耗时（秒），默认 0。
                    "description": """Duration to move to the target in seconds (default 0).""",
                    "default": 0.0,
                },
            },
            "required": [],
        },
    },
    handler=_handle_gui_mouse_click,
    emoji="🖱️",
)

# 4
registry.register(
    name="gui_mouse_drag",
    toolset="extools",
    schema={
        # 从起始坐标拖拽到目标坐标。
        #
        # ## 前置条件
        # 必须安装 pyautogui。
        # 当前环境需要有 GUI 桌面。
        #
        # ## 调用效果
        # 按住指定按键从 (start_x, start_y) 拖拽到 (end_x, end_y)。
        # start_x/start_y 默认使用当前鼠标位置。
        #
        # ## 返回
        # ```json
        # {"start": {"x": 0, "y": 0}, "end": {"x": 100, "y": 100}, "message": "Dragged from (0, 0) to (100, 100)"}
        # ```
        #
        # ## 何时使用
        # - 文本选择、文件拖动、窗口移动、滑块操作。
        #
        # ## 副作用/注意
        # - 会实际移动鼠标并触发拖拽。
        # - 起始和目标坐标必须在屏幕范围内。
        "description": """Drag the mouse from start to target coordinates.

## Prerequisites
pyautogui must be installed. The current environment must have a GUI desktop.

## Effect
Holds the specified button and drags from (start_x, start_y) to (end_x, end_y). start_x/start_y default to the current cursor position.

## Returns
```json
{"start": {"x": 0, "y": 0}, "end": {"x": 100, "y": 100}, "message": "Dragged from (0, 0) to (100, 100)"}
```

## When to Use
- Select text, drag files, move windows, or operate sliders.

## Side Effects / Notes
- Physically moves the mouse and triggers a drag operation.
- Start and target coordinates must be within the screen bounds.""",
        "parameters": {
            "type": "object",
            "properties": {
                "start_x": {"type": "integer", "description": """Start X coordinate. Defaults to current position."""},
                "start_y": {"type": "integer", "description": """Start Y coordinate. Defaults to current position."""},
                "end_x": {"type": "integer", "description": """Target X coordinate (required)."""},
                "end_y": {"type": "integer", "description": """Target Y coordinate (required)."""},
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    # 拖拽按键，默认 left。
                    "description": """Drag button, default left.""",
                    "default": "left",
                },
                "duration": {
                    "type": "number",
                    # 拖拽耗时（秒），默认 0.5。
                    "description": """Drag duration in seconds (default 0.5).""",
                    "default": 0.5,
                },
            },
            "required": ["end_x", "end_y"],
        },
    },
    handler=_handle_gui_mouse_drag,
    emoji="🖱️",
)

# 5
registry.register(
    name="gui_mouse_scroll",
    toolset="extools",
    schema={
        # 在指定位置或当前鼠标位置滚动滚轮。
        #
        # ## 前置条件
        # 必须安装 pyautogui。
        # 当前环境需要有 GUI 桌面。
        #
        # ## 调用效果
        # 滚动鼠标滚轮指定格数。正值向上滚动，负值向下滚动。
        #
        # ## 返回
        # ```json
        # {"direction": "up", "amount": 3, "message": "Scrolled 3 notch(es) up"}
        # ```
        #
        # ## 何时使用
        # - 滚动网页、文档或列表查看隐藏内容。
        #
        # ## 副作用/注意
        # - 一次滚动一格通常对应一行，具体取决于目标应用。
        "description": """Scroll the mouse wheel at a specified position or the current position.

## Prerequisites
pyautogui must be installed. The current environment must have a GUI desktop.

## Effect
Scrolls the mouse wheel by the specified number of notches. Positive values scroll up; negative values scroll down.

## Returns
```json
{"direction": "up", "amount": 3, "message": "Scrolled 3 notch(es) up"}
```

## When to Use
- Scroll web pages, documents, or lists to reveal hidden content.

## Side Effects / Notes
- One notch typically scrolls one line, but behavior depends on the target application.""",
        "parameters": {
            "type": "object",
            "properties": {
                "clicks": {
                    "type": "integer",
                    # 滚动格数，正=向上，负=向下，默认 3。
                    "description": """Scroll notches, positive=up, negative=down, default 3.""",
                    "default": 3,
                },
                "x": {"type": "integer", "description": """Scroll position X coordinate. Omit to use the current mouse position."""},
                "y": {"type": "integer", "description": """Scroll position Y coordinate. Omit to use the current mouse position."""},
            },
            "required": [],
        },
    },
    handler=_handle_gui_mouse_scroll,
    emoji="🖱️",
)

# 6
registry.register(
    name="gui_type",
    toolset="extools",
    schema={
        # 模拟键盘输入文本。
        #
        # ## 前置条件
        # 必须安装 pyautogui。
        # 当前环境需要有 GUI 桌面，且目标输入框应已聚焦。
        #
        # ## 调用效果
        # 在当前聚焦窗口中逐个字符输入 text。interval 控制字符间延迟。
        #
        # ## 返回
        # ```json
        # {"length": 12, "message": "Typed 12 character(s)"}
        # ```
        #
        # ## 何时使用
        # - 在文本框中输入内容。
        # - 模拟用户打字行为。
        #
        # ## 副作用/注意
        # - 非 ASCII 字符可能无法正确输入。
        # - 输入目标取决于当前焦点窗口，错误焦点会导致输入到错误位置。
        "description": """Simulate keyboard text input.

## Prerequisites
pyautogui must be installed. The current environment must have a GUI desktop, and the target input field should already be focused.

## Effect
Types the provided text character by character into the currently focused window. interval controls the delay between characters.

## Returns
```json
{"length": 12, "message": "Typed 12 character(s)"}
```

## When to Use
- Enter text into an input field.
- Simulate realistic typing behavior.

## Side Effects / Notes
- Non-ASCII characters may not be entered correctly.
- The input target depends on the current focus; incorrect focus may send text to the wrong window.""",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    # 要输入的文本。
                    "description": """Text to type.""",
                },
                "interval": {
                    "type": "number",
                    # 字符间延迟（秒），默认 0（最快）。
                    "description": """Delay between characters in seconds (default 0, fastest).""",
                    "default": 0.0,
                },
            },
            "required": ["text"],
        },
    },
    handler=_handle_gui_type,
    emoji="⌨️",
)

# 7
registry.register(
    name="gui_press_keys",
    toolset="extools",
    schema={
        # 按下单个键或组合键。
        #
        # ## 前置条件
        # 必须安装 pyautogui。
        # 当前环境需要有 GUI 桌面。
        #
        # ## 调用效果
        # 单个键：按一次，如 ["enter"]。
        # 组合键：同时按下多个键，如 ["ctrl", "c"] 表示 Ctrl+C。
        #
        # ## 返回
        # ```json
        # {"keys": ["ctrl", "c"], "combination": "ctrl+c", "message": "Pressed combo: ctrl+c"}
        # ```
        #
        # ## 何时使用
        # - 触发快捷键（复制、粘贴、保存等）。
        # - 按导航键（Esc、Tab、方向键等）。
        #
        # ## 副作用/注意
        # - 会实际触发键盘事件。
        # - 组合键顺序不影响执行，但通常将修饰键放前面。
        "description": """Press a single key or key combination.

## Prerequisites
pyautogui must be installed. The current environment must have a GUI desktop.

## Effect
Presses a single key once (e.g. ["enter"]) or a combination of keys simultaneously (e.g. ["ctrl", "c"] for Ctrl+C).

## Returns
```json
{"keys": ["ctrl", "c"], "combination": "ctrl+c", "message": "Pressed combo: ctrl+c"}
```

## When to Use
- Trigger keyboard shortcuts (copy, paste, save, etc.).
- Press navigation keys (Esc, Tab, arrow keys, etc.).

## Side Effects / Notes
- Actually triggers keyboard events.
- Order of keys in a combination does not affect execution, but modifier keys are conventionally listed first.""",
        "parameters": {
            "type": "object",
            "properties": {
                "keys": {
                    "oneOf": [
                        {"type": "string", "description": """Single key name, e.g. "enter"."""},
                        {"type": "array", "items": {"type": "string"},
                         "description": """List of key names, e.g. ["ctrl", "c"]."""},
                    ],
                    # 要按下的键或组合键。
                    "description": """Key or key combination to press.""",
                },
            },
            "required": ["keys"],
        },
    },
    handler=_handle_gui_press_keys,
    emoji="⌨️",
)

# 8
registry.register(
    name="gui_get_mouse_position",
    toolset="extools",
    schema={
        # 获取当前鼠标屏幕坐标。
        #
        # ## 前置条件
        # 必须安装 pyautogui。
        #
        # ## 调用效果
        # 返回当前鼠标光标的 (x, y) 坐标。
        #
        # ## 返回
        # ```json
        # {"x": 100, "y": 200, "message": "Mouse position: (100, 200)"}
        # ```
        #
        # ## 何时使用
        # - 在截图定位后确认当前鼠标位置。
        # - 需要记录或调试鼠标坐标时。
        "description": """Get the current mouse screen coordinates.

## Prerequisites
pyautogui must be installed.

## Effect
Returns the current (x, y) coordinates of the mouse cursor.

## Returns
```json
{"x": 100, "y": 200, "message": "Mouse position: (100, 200)"}
```

## When to Use
- Confirm the current mouse position after locating an element in a screenshot.
- Record or debug mouse coordinates.""",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    handler=_handle_gui_get_mouse_position,
    emoji="🖱️",
)

# 9
registry.register(
    name="gui_get_screen_size",
    toolset="extools",
    schema={
        # 获取主显示器分辨率。
        #
        # ## 前置条件
        # 必须安装 pyautogui。
        #
        # ## 调用效果
        # 返回主屏幕的宽度和高度（像素）。
        #
        # ## 返回
        # ```json
        # {"width": 1920, "height": 1080, "message": "Screen resolution: 1920 x 1080"}
        # ```
        #
        # ## 何时使用
        # - 计算截图或鼠标坐标的边界范围。
        # - 确认当前显示器的分辨率。
        "description": """Get the primary monitor resolution.

## Prerequisites
pyautogui must be installed.

## Effect
Returns the width and height of the primary screen in pixels.

## Returns
```json
{"width": 1920, "height": 1080, "message": "Screen resolution: 1920 x 1080"}
```

## When to Use
- Calculate bounds for screenshots or mouse coordinates.
- Confirm the current monitor resolution.""",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    handler=_handle_gui_get_screen_size,
    emoji="🖥️",
)

# 10
registry.register(
    name="gui_get_windows",
    toolset="extools",
    schema={
        # 列出系统中的可见窗口。
        #
        # ## 前置条件
        # 必须安装 pyautogui 和 pygetwindow。
        # 当前环境需要有 GUI 桌面。
        #
        # ## 调用效果
        # 返回可见窗口列表，包含标题、位置、大小和可见性。
        # 可通过 title 进行大小写不敏感的部分匹配过滤。
        #
        # ## 返回
        # ```json
        # {"count": 5, "windows": [{"title": "...", "left": 0, "top": 0, "width": 800, "height": 600, "visible": true}], "filter": "...", "message": "Found 5 matching window(s)"}
        # ```
        #
        # ## 何时使用
        # - 查找目标窗口标题。
        # - 在 gui_focus_window 前确认窗口存在。
        #
        # ## 副作用/注意
        # - 纯查询，不会修改窗口状态。
        # - 部分窗口可能没有标题。
        "description": """List all visible windows on the system.

## Prerequisites
pyautogui and pygetwindow must be installed. The current environment must have a GUI desktop.

## Effect
Returns a list of visible windows with title, position, size, and visibility. Can be filtered by title using a case-insensitive partial match.

## Returns
```json
{"count": 5, "windows": [{"title": "...", "left": 0, "top": 0, "width": 800, "height": 600, "visible": true}], "filter": "...", "message": "Found 5 matching window(s)"}
```

## When to Use
- Find the title of a target window.
- Confirm a window exists before calling gui_focus_window.

## Side Effects / Notes
- Read-only query; does not modify window state.
- Some windows may not have a title.""",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    # 窗口标题过滤关键字（部分匹配），留空则列出所有窗口。
                    "description": """Window title filter keyword (partial match), leave empty to list all.""",
                },
                "max_results": {
                    "type": "integer",
                    # 最大返回窗口数，默认 50。
                    "description": """Max windows to return (default 50).""",
                    "default": 50,
                },
            },
            "required": [],
        },
    },
    handler=_handle_gui_get_windows,
    emoji="🪟",
)

# 11
registry.register(
    name="gui_focus_window",
    toolset="extools",
    schema={
        # 根据标题查找窗口并将其置于前台。
        #
        # ## 前置条件
        # 必须安装 pyautogui 和 pygetwindow。
        # 当前环境需要有 GUI 桌面。
        # 目标窗口必须存在；建议先用 gui_get_windows 确认。
        #
        # ## 调用效果
        # 按标题部分匹配找到窗口并激活/聚焦。标题匹配为大小写不敏感的部分匹配。
        #
        # ## 返回
        # ```json
        # {"title": "My Window", "position": {"left": 0, "top": 0}, "size": {"width": 800, "height": 600}, "message": "Focused window: My Window"}
        # ```
        #
        # ## 何时使用
        # - 在操作窗口前确保其为活动窗口。
        # - 切换应用到前台以便截图或输入。
        #
        # ## 副作用/注意
        # - 会改变当前活动窗口。
        # - 如果找不到匹配窗口会返回错误。
        # - 某些环境下窗口聚焦可能失败，需要用户手动切换。
        "description": """Find a window by title and bring it to the foreground.

## Prerequisites
pyautogui and pygetwindow must be installed. The current environment must have a GUI desktop. The target window must exist; use gui_get_windows first if unsure.

## Effect
Finds a window by case-insensitive partial title match and activates/focuses it.

## Returns
```json
{"title": "My Window", "position": {"left": 0, "top": 0}, "size": {"width": 800, "height": 600}, "message": "Focused window: My Window"}
```

## When to Use
- Ensure a window is active before operating on it.
- Switch an application to the foreground for screenshot or input.

## Side Effects / Notes
- Changes the currently active window.
- Returns an error if no matching window is found.
- Window focus may fail in some environments; the user may need to switch manually.""",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    # 窗口标题关键字（部分匹配）。
                    "description": """Window title keyword (partial match).""",
                },
                "bring_to_front": {
                    "type": "boolean",
                    # 是否将窗口置于最前（默认 true）。
                    "description": """Whether to bring the window to front (default true).""",
                    "default": True,
                },
            },
            "required": ["title"],
        },
    },
    handler=_handle_gui_focus_window,
    emoji="🪟",
)

# 12
registry.register(
    name="gui_get_active_window",
    toolset="extools",
    schema={
        # 获取当前活动（前台）窗口的信息。
        #
        # ## 前置条件
        # 必须安装 pyautogui 和 pygetwindow。
        # 当前环境需要有 GUI 桌面。
        #
        # ## 调用效果
        # 返回当前活动窗口的标题、位置和大小。
        #
        # ## 返回
        # ```json
        # {"title": "My Window", "left": 0, "top": 0, "width": 800, "height": 600, "message": "Active window: My Window (800x600)"}
        # ```
        #
        # ## 何时使用
        # - 确认当前聚焦的是哪个窗口。
        # - 获取活动窗口尺寸以计算截图区域。
        #
        # ## 副作用/注意
        # - 纯查询，不会修改窗口状态。
        # - 无 GUI 环境或无前台窗口时会失败。
        "description": """Get info about the currently active (foreground) window.

## Prerequisites
pyautogui and pygetwindow must be installed. The current environment must have a GUI desktop.

## Effect
Returns the title, position, and size of the currently active window.

## Returns
```json
{"title": "My Window", "left": 0, "top": 0, "width": 800, "height": 600, "message": "Active window: My Window (800x600)"}
```

## When to Use
- Confirm which window currently has focus.
- Get the active window's dimensions to calculate screenshot regions.

## Side Effects / Notes
- Read-only query; does not modify window state.
- Fails in headless environments or when there is no foreground window.""",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    handler=_handle_gui_get_active_window,
    emoji="🪟",
)

# 13
registry.register(
    name="gui_locate_on_screen",
    toolset="extools",
    schema={
        # 在屏幕上查找匹配的模板图片。
        #
        # ## 前置条件
        # 必须安装 pyautogui 和 opencv-python（用于 confidence 参数）。
        # 当前环境需要有 GUI 桌面。
        # 模板图片必须存在，支持 ws: 前缀或本地绝对路径。
        #
        # ## 调用效果
        # 在屏幕上搜索与模板图片匹配的区域，返回匹配区域和中心坐标。
        # confidence 为匹配置信度阈值（0-1），默认 0.9。
        #
        # ## 返回
        # ```json
        # {"found": true, "location": {"left": 100, "top": 100, "width": 50, "height": 50}, "center": {"x": 125, "y": 125}, "message": "Match found, center: (125, 125)"}
        # ```
        #
        # ## 何时使用
        # - 在 GUI 自动化中通过图像定位难以用坐标确定的元素。
        # - 找到按钮、图标后配合 gui_mouse_click 点击。
        #
        # ## 副作用/注意
        # - 纯查询，不会移动鼠标或点击。
        # - 屏幕分辨率或主题变化可能导致匹配失败。
        # - confidence 越高越严格，可能漏匹配；越低越容易误匹配。
        "description": """Find a matching template image on screen.

## Prerequisites
pyautogui and opencv-python (for the confidence parameter) must be installed. The current environment must have a GUI desktop. The template image must exist; supports ws: prefix or local absolute path.

## Effect
Searches the screen for a region matching the template image and returns the match region and center coordinates. confidence is the matching threshold (0-1), default 0.9.

## Returns
```json
{"found": true, "location": {"left": 100, "top": 100, "width": 50, "height": 50}, "center": {"x": 125, "y": 125}, "message": "Match found, center: (125, 125)"}
```

## When to Use
- Locate elements by image in GUI automation when coordinates are unreliable.
- Find a button or icon and then click it with gui_mouse_click.

## Side Effects / Notes
- Read-only query; does not move the mouse or click.
- Screen resolution or theme changes may cause matches to fail.
- Higher confidence is stricter and may miss matches; lower confidence may produce false matches.""",
        "parameters": {
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    # 模板图片路径，支持 ws: 前缀或本地绝对路径。
                    "description": """Template image path, supports ws: prefix or local absolute path.""",
                },
                "confidence": {
                    "type": "number",
                    # 匹配置信度 0-1，默认 0.9。需要 opencv-python 才能使用。
                    "description": """Confidence threshold 0-1, default 0.9. Requires opencv-python.""",
                    "default": 0.9,
                },
            },
            "required": ["image_path"],
        },
    },
    handler=_handle_gui_locate_on_screen,
    emoji="🔍",
)