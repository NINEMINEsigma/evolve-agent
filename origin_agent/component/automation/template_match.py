"""模板匹配工具 — 在截图中用 OpenCV 模板匹配定位目标，返回匹配坐标框选。

模块导入时通过 ``registry.register()`` 注册。

依赖 ``opencv-python`` 和 ``numpy``。通过 ``check_fn`` 检测 cv2 可用性。
参考 MAA 的 TemplateMatch 算法设计，支持 ROI 区域限定和多匹配结果。
"""

from __future__ import annotations

import logging
from typing import * # type: ignore

from abstract.tools.registry import registry, tool_error, tool_result
from system.sandbox import SandboxError

if TYPE_CHECKING:
    from cv2.typing import MatLike


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 依赖检测
# ---------------------------------------------------------------------------


def _try_import(module_name: str) -> bool:
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


def _check_cv2() -> bool:
    return _try_import("cv2")


# ---------------------------------------------------------------------------
# 沙箱引用
# ---------------------------------------------------------------------------

from component.tools.filesystem import _s as _get_sandbox  # noqa: E402


def _s():
    return _get_sandbox()


def _imread_unicode(path: str, flags: int) -> "MatLike | None":
    """读取可能包含非 ASCII 字符路径的图片。

    cv2.imread 在 Windows 上使用 C 标准 API 打开文件，
    不支持 Unicode 路径（如中文文件名）。
    使用 numpy.fromfile + cv2.imdecode 替代。
    """
    import cv2
    import numpy as np

    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, flags)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def _handle_template_match(args: dict[str, Any]) -> dict:
    """在截图中用 OpenCV 模板匹配定位目标。"""
    import cv2
    import numpy as np

    screenshot_path: str = str(args.get("screenshot_path", "")).strip()
    template_path: str = str(args.get("template_path", "")).strip()
    threshold: float = float(args.get("threshold", 0.7))
    roi: list[int] | None = args.get("roi")
    method: int = int(args.get("method", cv2.TM_CCOEFF_NORMED))

    # 参数校验
    if not screenshot_path:
        return tool_error("screenshot_path is required")
    if not template_path:
        return tool_error("template_path is required")
    if threshold < 0 or threshold > 1:
        return tool_error(f"threshold must be in [0, 1], got {threshold}")

    # 通过沙箱解析路径并读取图片
    try:
        ss_resolved = _s().resolve_read(screenshot_path)
        tpl_resolved = _s().resolve_read(template_path)
    except SandboxError as exc:
        return tool_error(str(exc), screenshot_path=screenshot_path, template_path=template_path)

    if not ss_resolved.real.is_file():
        return tool_error(f"Screenshot not found: {screenshot_path}", screenshot_path=screenshot_path)
    if not tpl_resolved.real.is_file():
        return tool_error(f"Template not found: {template_path}", template_path=template_path)

    # 加载图片
    screenshot = _imread_unicode(str(ss_resolved.real), cv2.IMREAD_COLOR)
    template = _imread_unicode(str(tpl_resolved.real), cv2.IMREAD_COLOR)

    if screenshot is None:
        return tool_error(f"Failed to read screenshot: {screenshot_path}", screenshot_path=screenshot_path)
    if template is None:
        return tool_error(f"Failed to read template: {template_path}", template_path=template_path)

    # ROI 区域裁剪
    roi_offset_x: int = 0
    roi_offset_y: int = 0
    search_area = screenshot

    if roi is not None:
        if not isinstance(roi, list) or len(roi) != 4:
            return tool_error("roi must be [x, y, w, h] (4 integers)")
        rx, ry, rw, rh = roi
        # 坐标边界检查
        h_img, w_img = screenshot.shape[:2]
        if rx < 0 or ry < 0 or rw <= 0 or rh <= 0:
            return tool_error(f"roi values must be non-negative and w,h > 0, got {roi}")
        if rx + rw > w_img or ry + rh > h_img:
            return tool_error(
                f"roi [{rx},{ry},{rw},{rh}] exceeds screenshot bounds ({w_img}x{h_img})",
                screenshot_path=screenshot_path,
            )
        search_area = screenshot[ry:ry + rh, rx:rx + rw]
        roi_offset_x = rx
        roi_offset_y = ry

    # 模板尺寸检查
    th, tw = template.shape[:2]
    sh, sw = search_area.shape[:2]
    if tw > sw or th > sh:
        return tool_error(
            f"Template ({tw}x{th}) is larger than search area ({sw}x{sh})",
            screenshot_path=screenshot_path,
            template_path=template_path,
        )

    # 执行模板匹配
    result = cv2.matchTemplate(search_area, template, method)

    # 根据匹配方法判断使用最大值还是最小值
    # SQDIFF 和 SQDIFF_NORMED 用最小值，其余用最大值
    use_max = method not in (cv2.TM_SQDIFF, cv2.TM_SQDIFF_NORMED)

    # 收集所有超过阈值的结果（多匹配）
    matches: list[dict] = []

    if use_max:
        # 对于 CCORR/CCOEFF 系列，值越大越匹配
        locs = np.where(result >= threshold)
    else:
        # 对于 SQDIFF 系列，值越小越匹配
        locs = np.where(result <= (1.0 - threshold))

    for pt in zip(*locs[::-1]):
        # 将 ROI 内的坐标转换回原图坐标
        x = int(pt[0]) + roi_offset_x
        y = int(pt[1]) + roi_offset_y
        score = float(result[pt[1], pt[0]])
        if not use_max:
            score = 1.0 - score  # SQDIFF 反转分数
        matches.append({"x": x, "y": y, "w": tw, "h": th, "score": round(score, 4)})

    # 去重：合并相邻的匹配点（NMS 简化版）
    matches = _nms(matches, tw, th)

    # 按分数降序排序
    matches.sort(key=lambda m: m["score"], reverse=True)

    best_match = matches[0] if matches else None

    logger.info(
        "template_match | screenshot=%s template=%s threshold=%.2f → %d matches, best_score=%.4f",
        screenshot_path, template_path, threshold, len(matches),
        best_match["score"] if best_match else 0,
    )

    return tool_result(
        success=True,
        matched=len(matches) > 0,
        match_count=len(matches),
        matches=matches,
        best=best_match,
        screenshot_path=screenshot_path,
        template_path=template_path,
        threshold=threshold,
    )


def _nms(matches: list[dict], tw: int, th: int, overlap_thresh: float = 0.5) -> list[dict]:
    """简化版非极大值抑制，合并重叠的匹配框。

    按 score 降序排列，逐个保留，删除与已保留框重叠超过阈值的后续框。
    """
    if not matches:
        return matches

    # 按 score 降序排序
    matches.sort(key=lambda m: m["score"], reverse=True)

    kept: list[dict] = []
    for m in matches:
        is_dup = False
        for k in kept:
            # 计算重叠面积
            x1 = max(m["x"], k["x"])
            y1 = max(m["y"], k["y"])
            x2 = min(m["x"] + tw, k["x"] + tw)
            y2 = min(m["y"] + th, k["y"] + th)
            inter = max(0, x2 - x1) * max(0, y2 - y1)
            area = tw * th
            if area > 0 and inter / area >= overlap_thresh:
                is_dup = True
                break
        if not is_dup:
            kept.append(m)

    return kept


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

registry.register(
    name="template_match",
    toolset="automation",
    schema={
        # 在截图中用 OpenCV 模板匹配定位目标，返回匹配坐标框选。
        # 前置条件：需安装 opencv-python；截图和模板图片须在沙箱（ws:）中。
        # 调用效果：使用 cv2.matchTemplate 查找模板，返回阈值以上的所有匹配并按分数降序排列。
        # 返回值：matched、match_count、matches 列表、best 最佳匹配。
        # 典型场景：screen_capture 截图后定位 UI 元素，为 mouse_click 提供坐标。
        # 副作用：只读操作，不修改文件；NMS 去重重叠率 >50% 的匹配。
        "description": """Find a template image within a screenshot using OpenCV template matching.

## Prerequisites
- `opencv-python` (cv2) must be installed.
- Both screenshot and template images must exist in agentspace (ws: namespace).
- Template must be smaller than or equal to the screenshot (or ROI area).

## Effect
Uses `cv2.matchTemplate` to locate the template image within the screenshot. Returns all matching locations above the threshold, sorted by score (descending). Non-maximum suppression (NMS) is applied to remove duplicate matches.

## Returns
```json
{
  "success": true,
  "matched": true,
  "match_count": 3,
  "matches": [
    {"x": 100, "y": 200, "w": 50, "h": 30, "score": 0.95},
    {"x": 300, "y": 200, "w": 50, "h": 30, "score": 0.85}
  ],
  "best": {"x": 100, "y": 200, "w": 50, "h": 30, "score": 0.95},
  "screenshot_path": "ws:uploads/screenshot_001.png",
  "template_path": "ws:uploads/button.png",
  "threshold": 0.7
}
```
`x, y` is the top-left corner of the match in the original screenshot coordinate system. `w, h` is the template dimensions. `score` is the match confidence (0-1, higher is better).

When `matched` is false, `matches` is empty and `best` is null.

## When to Use
- After `screen_capture` to locate UI elements (buttons, icons, text regions) on screen.
- To find coordinates for `mouse_click` — use the `best` match's center: `x + w/2`, `y + h/2`.
- To verify whether a specific UI state is present.

## ROI (Region of Interest)
Optional `roi` parameter limits the search area to `[x, y, w, h]` within the screenshot. This speeds up matching and reduces false positives. Returned coordinates are in the original screenshot's coordinate system.

## Side Effects / Notes
- Read-only operation — does not modify any files.
- Requires `opencv-python` and `numpy` installed.
- Default matching method is `TM_CCOEFF_NORMED` (method=5), which is illumination-invariant and recommended by MAA.
- NMS overlap threshold is 0.5 — matches overlapping by more than 50% are deduplicated.""",
        "parameters": {
            "type": "object",
            "properties": {
                "screenshot_path": {
                    "type": "string",
                    # 截图图片的沙箱路径（ws: 命名空间，如 ws:uploads/screenshot_001.png）。
                    "description": "Sandbox path of the screenshot image (ws: namespace, e.g. 'ws:uploads/screenshot_001.png').",
                },
                "template_path": {
                    "type": "string",
                    # 模板图片的沙箱路径（ws: 命名空间，如 ws:uploads/button.png）。
                    "description": "Sandbox path of the template image to search for (ws: namespace, e.g. 'ws:uploads/button.png').",
                },
                "threshold": {
                    "type": "number",
                    # 匹配置信度阈值（0-1），仅返回分数 >= 阈值的匹配，默认 0.7。
                    "description": "Match confidence threshold (0-1). Only matches with score >= threshold are returned. Default: 0.7.",
                    "default": 0.7,
                },
                "roi": {
                    "type": "array",
                    "items": {"type": "integer"},
                    # 感兴趣区域 [x, y, w, h]，限定截图内的搜索范围，加速匹配并减少误匹配，默认全图。
                    "description": "Region of interest [x, y, w, h] to limit the search area within the screenshot. Default: full image.",
                },
                "method": {
                    "type": "integer",
                    # OpenCV 模板匹配方法，默认 5（TM_CCOEFF_NORMED），详见 cv2.TemplateMatchModes 文档。
                    "description": "OpenCV template matching method. Default: 5 (TM_CCOEFF_NORMED). See cv2.TemplateMatchModes docs.",
                    "default": 5,
                },
            },
            "required": ["screenshot_path", "template_path"],
        },
    },
    handler=_handle_template_match,
    check_fn=_check_cv2,
    emoji="🎯",
)