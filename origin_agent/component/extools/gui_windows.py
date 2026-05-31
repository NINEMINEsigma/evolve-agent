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

from abstract.tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 延迟导入 — 避免启动时强制要求 GUI 依赖
# ---------------------------------------------------------------------------

_pyautogui = None
_pygetwindow = None
_Image = None

def _ensure_deps():
    """按需导入 GUI 操纵库，失败时抛出明确错误。"""
    global _pyautogui, _pygetwindow, _Image
    if _pyautogui is None:
        try:
            import pyautogui as pag
            _pyautogui = pag
        except ImportError:
            raise ImportError(
                "pyautogui 未安装。请运行: pip install pyautogui"
            )
    if _pygetwindow is None:
        try:
            import pygetwindow as gw
            _pygetwindow = gw
        except ImportError:
            raise ImportError(
                "pygetwindow 未安装。请运行: pip install pygetwindow"
            )
    if _Image is None:
        try:
            from PIL import Image as PILImage
            _Image = PILImage
        except ImportError:
            raise ImportError(
                "Pillow 未安装。请运行: pip install Pillow"
            )


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

def _save_screenshot(img, filename: str | None = None) -> tuple[str, str, int]:
    """将 PIL Image 保存到 ws:screenshots/ 下，返回 (ws_path, b64, size_bytes)。"""
    _ensure_deps()
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

def _handle_gui_screenshot(args: Dict[str, Any]) -> str:
    _ensure_deps()

    region = args.get("region")  # [x, y, w, h] or None
    filename: str = str(args.get("filename", "")).strip() or None

    if region is not None:
        if not (isinstance(region, list) and len(region) == 4):
            return tool_error("region 必须是 [x, y, width, height] 格式的列表")
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
        base64_preview=b64[:200] + "..." if len(b64) > 200 else b64,
        message=f"截图已保存: {ws_path} ({img.width}x{img.height}, {size_bytes/1024:.1f} KB)",
    )


# ---------------------------------------------------------------------------
# 2. gui_mouse_move
# ---------------------------------------------------------------------------

def _handle_gui_mouse_move(args: Dict[str, Any]) -> str:
    _ensure_deps()

    x: int = int(args["x"])
    y: int = int(args["y"])
    duration: float = float(args.get("duration", 0.3))

    _pyautogui.moveTo(x, y, duration=duration)
    actual = _pyautogui.position()

    return tool_result(
        target={"x": x, "y": y},
        actual={"x": actual.x, "y": actual.y},
        message=f"鼠标已移动到 ({actual.x}, {actual.y})",
    )


# ---------------------------------------------------------------------------
# 3. gui_mouse_click
# ---------------------------------------------------------------------------

def _handle_gui_mouse_click(args: Dict[str, Any]) -> str:
    _ensure_deps()

    x = args.get("x")
    y = args.get("y")
    button: str = str(args.get("button", "left")).lower()
    clicks: int = int(args.get("clicks", 1))
    interval: float = float(args.get("interval", 0.0))
    duration: float = float(args.get("duration", 0.0))

    if button not in ("left", "right", "middle"):
        return tool_error(f"无效的按键类型: {button}（支持 left/right/middle）")
    if clicks < 1 or clicks > 3:
        return tool_error(f"点击次数无效: {clicks}（支持 1-3）")

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
        message=f"已{button}键单击 {pos_msg}，共{clicks}次",
    )


# ---------------------------------------------------------------------------
# 4. gui_mouse_drag
# ---------------------------------------------------------------------------

def _handle_gui_mouse_drag(args: Dict[str, Any]) -> str:
    _ensure_deps()

    start_x: int = int(args.get("start_x", args.get("x", 0)))
    start_y: int = int(args.get("start_y", args.get("y", 0)))
    end_x: int = int(args["end_x"])
    end_y: int = int(args["end_y"])
    button: str = str(args.get("button", "left")).lower()
    duration: float = float(args.get("duration", 0.5))

    if button not in ("left", "right", "middle"):
        return tool_error(f"无效的按键类型: {button}")

    _pyautogui.moveTo(start_x, start_y, duration=0.1)
    _pyautogui.drag(end_x - start_x, end_y - start_y,
                    duration=duration, button=button)

    return tool_result(
        start={"x": start_x, "y": start_y},
        end={"x": end_x, "y": end_y},
        message=f"已从 ({start_x}, {start_y}) 拖拽到 ({end_x}, {end_y})",
    )


# ---------------------------------------------------------------------------
# 5. gui_mouse_scroll
# ---------------------------------------------------------------------------

def _handle_gui_mouse_scroll(args: Dict[str, Any]) -> str:
    _ensure_deps()

    clicks: int = int(args.get("clicks", 3))
    x = args.get("x")
    y = args.get("y")

    if x is not None and y is not None:
        _pyautogui.scroll(clicks, int(x), int(y))
    else:
        _pyautogui.scroll(clicks)

    direction = "上" if clicks > 0 else "下"
    return tool_result(
        direction=direction,
        amount=abs(clicks),
        message=f"滚轮{direction}滚动了 {abs(clicks)} 格",
    )


# ---------------------------------------------------------------------------
# 6. gui_type
# ---------------------------------------------------------------------------

def _handle_gui_type(args: Dict[str, Any]) -> str:
    _ensure_deps()

    text: str = str(args["text"])
    interval: float = float(args.get("interval", 0.0))

    _pyautogui.typewrite(text, interval=interval)

    return tool_result(
        length=len(text),
        message=f"已输入 {len(text)} 个字符",
    )


# ---------------------------------------------------------------------------
# 7. gui_press_keys
# ---------------------------------------------------------------------------

def _handle_gui_press_keys(args: Dict[str, Any]) -> str:
    _ensure_deps()

    keys = args.get("keys", [])

    if isinstance(keys, str):
        keys = [keys]
    if not isinstance(keys, list) or len(keys) == 0:
        return tool_error("keys 必须是非空列表，如 [\"ctrl\", \"c\"]")

    keys = [str(k) for k in keys]

    if len(keys) == 1:
        _pyautogui.press(keys[0])
        return tool_result(
            keys=keys,
            message=f"已按下: {keys[0]}",
        )
    else:
        _pyautogui.hotkey(*keys)
        return tool_result(
            keys=keys,
            combination="+".join(keys),
            message=f"已按下组合键: {'+'.join(keys)}",
        )


# ---------------------------------------------------------------------------
# 8. gui_get_mouse_position
# ---------------------------------------------------------------------------

def _handle_gui_get_mouse_position(_args: Dict[str, Any]) -> str:
    _ensure_deps()

    pos = _pyautogui.position()

    return tool_result(
        x=pos.x,
        y=pos.y,
        message=f"鼠标当前位置: ({pos.x}, {pos.y})",
    )


# ---------------------------------------------------------------------------
# 9. gui_get_screen_size
# ---------------------------------------------------------------------------

def _handle_gui_get_screen_size(_args: Dict[str, Any]) -> str:
    _ensure_deps()

    w, h = _pyautogui.size()

    return tool_result(
        width=w,
        height=h,
        message=f"屏幕分辨率: {w} x {h}",
    )


# ---------------------------------------------------------------------------
# 10. gui_get_windows
# ---------------------------------------------------------------------------

def _handle_gui_get_windows(args: Dict[str, Any]) -> str:
    _ensure_deps()

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
        message=f"找到 {len(results)} 个匹配窗口",
    )


# ---------------------------------------------------------------------------
# 11. gui_focus_window
# ---------------------------------------------------------------------------

def _handle_gui_focus_window(args: Dict[str, Any]) -> str:
    _ensure_deps()

    title: str = str(args["title"]).strip()
    bring_to_front: bool = bool(args.get("bring_to_front", True))

    if not title:
        return tool_error("title 是必填的")

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
        message=f"已聚焦窗口: {win.title}",
    )


# ---------------------------------------------------------------------------
# 12. gui_get_active_window
# ---------------------------------------------------------------------------

def _handle_gui_get_active_window(_args: Dict[str, Any]) -> str:
    _ensure_deps()

    try:
        win = _pygetwindow.getActiveWindow()
    except Exception:
        return tool_error("无法获取活动窗口信息")

    if win is None:
        return tool_error("无法获取活动窗口（可能没有 GUI 环境）")

    return tool_result(
        title=win.title,
        left=win.left,
        top=win.top,
        width=win.width,
        height=win.height,
        message=f"活动窗口: {win.title} ({win.width}x{win.height})",
    )


# ---------------------------------------------------------------------------
# 13. gui_locate_on_screen
# ---------------------------------------------------------------------------

def _handle_gui_locate_on_screen(args: Dict[str, Any]) -> str:
    _ensure_deps()

    image_path: str = str(args["image_path"]).strip()
    confidence: float = float(args.get("confidence", 0.9))

    if not image_path:
        return tool_error("image_path 是必填的 — 要查找的模板图片路径")

    # 支持 ws: 路径
    if image_path.startswith("ws:"):
        sb = _get_sandbox()
        try:
            r = sb.resolve_read(image_path)
            image_path = str(r.real)
        except Exception as e:
            return tool_error(f"无法解析路径 {image_path}: {e}")

    if not Path(image_path).exists():
        return tool_error(f"模板图片不存在: {image_path}")

    try:
        location = _pyautogui.locateOnScreen(image_path, confidence=confidence)
    except Exception as e:
        return tool_error(f"屏幕查找失败: {e}")

    if location is None:
        return tool_result(
            found=False,
            message=f"未在屏幕上找到匹配的图像（confidence={confidence}）",
        )

    center = _pyautogui.center(location)

    return tool_result(
        found=True,
        location={"left": location.left, "top": location.top,
                  "width": location.width, "height": location.height},
        center={"x": center.x, "y": center.y},
        message=f"找到匹配图像，中心点: ({center.x}, {center.y})",
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
        "description": (
            "截取屏幕截图并保存到 ws:screenshots/ 目录。\n"
            "可指定 region=[x, y, w, h] 截取部分区域，省略则截全屏。\n"
            "截图保存为 PNG 格式，返回 ws: 路径供 display_image 使用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 4,
                    "maxItems": 4,
                    "description": "截图区域 [x, y, width, height]，省略则截全屏",
                },
                "filename": {
                    "type": "string",
                    "description": "自定义文件名（不含路径），默认自动生成时间戳名称",
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
        "description": (
            "将鼠标移动到指定的屏幕坐标。\n"
            "duration 控制移动耗时（秒），默认 0.3 秒实现平滑移动。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                **_COORD_PROPS,
                "duration": {
                    "type": "number",
                    "description": "移动耗时（秒），默认 0.3",
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
        "description": (
            "在指定坐标或当前位置执行鼠标单击。\n"
            "不传 x/y 则在当前位置点击。\n"
            "button: left/right/middle，clicks: 1-3（双击传 2）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X 坐标，省略则在当前位置点击"},
                "y": {"type": "integer", "description": "Y 坐标，省略则在当前位置点击"},
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    "description": "鼠标按键，默认 left",
                    "default": "left",
                },
                "clicks": {
                    "type": "integer",
                    "description": "点击次数，1=单击 2=双击，默认 1",
                    "default": 1,
                },
                "interval": {
                    "type": "number",
                    "description": "多次点击间隔（秒），默认 0",
                    "default": 0.0,
                },
                "duration": {
                    "type": "number",
                    "description": "移动到目标位置的耗时（秒），默认 0",
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
        "description": (
            "从起始坐标拖拽鼠标到目标坐标。\n"
            "start_x/start_y 默认等于 x/y（或当前鼠标位置），end_x/end_y 为必填。\n"
            "用于选取文本、拖拽文件、移动窗口等操作。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "start_x": {"type": "integer", "description": "起始 X 坐标"},
                "start_y": {"type": "integer", "description": "起始 Y 坐标"},
                "end_x": {"type": "integer", "description": "目标 X 坐标（必填）"},
                "end_y": {"type": "integer", "description": "目标 Y 坐标（必填）"},
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    "description": "拖拽按键，默认 left",
                    "default": "left",
                },
                "duration": {
                    "type": "number",
                    "description": "拖拽耗时（秒），默认 0.5",
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
        "description": (
            "在指定位置或当前鼠标位置执行滚轮滚动。\n"
            "clicks 正值向上滚，负值向下滚，每格通常为一行。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "clicks": {
                    "type": "integer",
                    "description": "滚动格数，正=向上，负=向下，默认 3",
                    "default": 3,
                },
                "x": {"type": "integer", "description": "滚动位置的 X 坐标，省略则使用当前鼠标位置"},
                "y": {"type": "integer", "description": "滚动位置的 Y 坐标，省略则使用当前鼠标位置"},
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
        "description": (
            "模拟键盘输入文本。\n"
            "输入的文本将如同用户在键盘上逐键敲击一样发送到当前焦点窗口。\n"
            "interval 为每个字符之间的延迟（秒）。\n"
            "注意：非 ASCII 字符可能无法正确输入，此时建议用 gui_press_keys 配合剪贴板。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "要输入的文本",
                },
                "interval": {
                    "type": "number",
                    "description": "字符间延迟（秒），默认 0（最快）",
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
        "description": (
            "按下单个键或组合键。\n"
            "单个键: [\"enter\"] 或 [\"esc\"]\n"
            "组合键: [\"ctrl\", \"c\"] 表示 Ctrl+C\n"
            "可用键名: enter, space, tab, esc, backspace, delete, "
            "up, down, left, right, home, end, pageup, pagedown, "
            "f1-f12, ctrl, alt, shift, win, 以及所有字母和数字键。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "keys": {
                    "oneOf": [
                        {"type": "string", "description": "单个键名，如 \"enter\""},
                        {"type": "array", "items": {"type": "string"},
                         "description": "键名列表，如 [\"ctrl\", \"c\"]"},
                    ],
                    "description": "要按下的键或组合键",
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
        "description": "获取鼠标当前屏幕坐标，返回 {x, y}。",
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
        "description": "获取主显示器分辨率，返回 {width, height}。",
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
        "description": (
            "列出当前系统中所有可见窗口。\n"
            "可按 title 过滤（大小写不敏感的部分匹配）。\n"
            "返回窗口标题、位置、大小信息。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "窗口标题过滤关键字（部分匹配），留空则列出所有窗口",
                },
                "max_results": {
                    "type": "integer",
                    "description": "最大返回窗口数，默认 50",
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
        "description": (
            "按标题查找窗口并将其置于前台（聚焦）。\n"
            "title 为部分匹配（不区分大小写）。\n"
            "如果未找到匹配窗口，返回错误并建议先用 gui_get_windows 列出窗口。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "窗口标题关键字（部分匹配）",
                },
                "bring_to_front": {
                    "type": "boolean",
                    "description": "是否将窗口置于最前（默认 true）",
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
        "description": (
            "获取当前活动（前景）窗口的信息，包括标题、位置、大小。"
        ),
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
        "description": (
            "在屏幕中查找匹配模板图像的位置。\n"
            "image_path 可以是 ws: 路径或本地绝对路径。\n"
            "confidence 为匹配置信度（0-1），默认 0.9。\n"
            "找到则返回匹配区域和中心点坐标，未找到返回 found=false。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": "模板图片路径，支持 ws: 前缀或本地绝对路径",
                },
                "confidence": {
                    "type": "number",
                    "description": "匹配置信度 0-1，默认 0.9。需要 opencv-python 才能使用",
                    "default": 0.9,
                },
            },
            "required": ["image_path"],
        },
    },
    handler=_handle_gui_locate_on_screen,
    emoji="🔍",
)