"""模板匹配工具 — 在图片中用 OpenCV 模板匹配定位目标，返回匹配坐标框选。

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


def _match_single(
    image: "MatLike",
    template: "MatLike",
    threshold: float,
    roi: list[int] | None,
    method: int,
) -> dict:
    """对单张模板执行匹配，返回 matched / match_count / matches / best。"""
    import cv2
    import numpy as np

    # ROI 区域裁剪
    roi_offset_x: int = 0
    roi_offset_y: int = 0
    search_area = image

    if roi is not None:
        if not isinstance(roi, list) or len(roi) != 4:
            return {"error": "roi must be [x, y, w, h] (4 integers)"}
        rx, ry, rw, rh = roi
        h_img, w_img = image.shape[:2]
        if rx < 0 or ry < 0 or rw <= 0 or rh < 0:
            return {"error": f"roi values must be non-negative and w,h > 0, got {roi}"}
        if rx + rw > w_img or ry + rh > h_img:
            return {"error": f"roi [{rx},{ry},{rw},{rh}] exceeds image bounds ({w_img}x{h_img})"}
        search_area = image[ry:ry + rh, rx:rx + rw]
        roi_offset_x = rx
        roi_offset_y = ry

    # 模板尺寸检查
    th, tw = template.shape[:2]
    sh, sw = search_area.shape[:2]
    if tw > sw or th > sh:
        return {"error": f"Template ({tw}x{th}) is larger than search area ({sw}x{sh})"}

    # 执行模板匹配
    result = cv2.matchTemplate(search_area, template, method)
    use_max = method not in (cv2.TM_SQDIFF, cv2.TM_SQDIFF_NORMED)

    matches: list[dict] = []
    if use_max:
        locs = np.where(result >= threshold)
    else:
        locs = np.where(result < (1.0 - threshold))

    for pt in zip(*locs[::-1]):
        x = int(pt[0]) + roi_offset_x
        y = int(pt[1]) + roi_offset_y
        score = float(result[pt[1], pt[0]])
        if not use_max:
            score = 1.0 - score
        matches.append({"x": x, "y": y, "w": tw, "h": th, "score": round(score, 4)})

    matches = _nms(matches, tw, th)
    matches.sort(key=lambda m: m["score"], reverse=True)
    best_match = matches[0] if matches else None

    return {
        "matched": len(matches) > 0,
        "match_count": len(matches),
        "matches": matches,
        "best": best_match,
    }


def _handle_template_match(args: dict[str, Any]) -> dict:
    """在图片中用 OpenCV 模板匹配定位目标，支持多模板批量匹配。"""
    import cv2

    image_path: str = str(args.get("image", "")).strip()
    template_paths_raw = args.get("template_paths", [])
    threshold: float = float(args.get("threshold", 0.7))
    roi: list[int] | None = args.get("roi")
    method: int = int(args.get("method", cv2.TM_CCOEFF_NORMED))

    # 参数校验
    if not image_path:
        return tool_error("image is required")
    if not isinstance(template_paths_raw, list) or not template_paths_raw:
        return tool_error("template_paths is required as a non-empty array of strings")
    if threshold < 0 or threshold > 1:
        return tool_error(f"threshold must be in [0, 1], got {threshold}")

    template_paths = [str(tp).strip() for tp in template_paths_raw]

    # 通过沙箱解析源图路径并读取
    try:
        img_resolved = _s().resolve_read(image_path)
    except SandboxError as exc:
        return tool_error(str(exc), image=image_path)

    if not img_resolved.real.is_file():
        return tool_error(f"Image not found: {image_path}", image=image_path)

    image = _imread_unicode(str(img_resolved.real), cv2.IMREAD_COLOR)
    if image is None:
        return tool_error(f"Failed to read image: {image_path}", image=image_path)

    # 逐模板匹配
    results: dict[str, dict] = {}
    matched_count = 0

    for tp in template_paths:
        if not tp:
            results[tp] = {"matched": False, "match_count": 0, "matches": [], "best": None, "error": "template path is empty"}
            continue

        try:
            tpl_resolved = _s().resolve_read(tp)
        except SandboxError as exc:
            results[tp] = {"matched": False, "match_count": 0, "matches": [], "best": None, "error": str(exc)}
            continue

        if not tpl_resolved.real.is_file():
            results[tp] = {"matched": False, "match_count": 0, "matches": [], "best": None, "error": f"Template not found: {tp}"}
            continue

        template = _imread_unicode(str(tpl_resolved.real), cv2.IMREAD_COLOR)
        if template is None:
            results[tp] = {"matched": False, "match_count": 0, "matches": [], "best": None, "error": f"Failed to read template: {tp}"}
            continue

        single_result = _match_single(image, template, threshold, roi, method)
        if "error" in single_result:
            results[tp] = {"matched": False, "match_count": 0, "matches": [], "best": None, "error": single_result["error"]}
        else:
            results[tp] = single_result
            if single_result["matched"]:
                matched_count += 1

        logger.info(
            "template_match | image=%s template=%s → %d matches, best_score=%.4f",
            image_path, tp, single_result.get("match_count", 0),
            single_result["best"]["score"] if single_result.get("best") else 0,
        )

    total = len(results)
    return tool_result(
        success=True,
        image=image_path,
        results=results,
        summary={"total": total, "matched": matched_count, "unmatched": total - matched_count},
        threshold=threshold,
        roi=roi,
        method=method,
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
        # 在图片中用 OpenCV 模板匹配定位目标，返回匹配坐标框选。
        # 前置条件：需安装 opencv-python；图片和模板须在沙箱（ws:）中。
        # 调用效果：对每张模板执行 cv2.matchTemplate，返回阈值以上的所有匹配并按分数降序排列。
        # 返回值：results 以模板路径为键，每项含 matched、match_count、matches 列表、best 最佳匹配。
        # 典型场景：screen_capture 截图后定位 UI 元素，为 mouse_click 提供坐标。
        # 副作用：只读操作，不修改文件；NMS 去重重叠率 >50% 的匹配。
        "description": """Find template images within an image using OpenCV template matching.

## Prerequisites
- `opencv-python` (cv2) must be installed.
- Both the source image and template images must exist in agentspace (ws: namespace).
- Each template must be smaller than or equal to the source image (or ROI area).

## Effect
Uses `cv2.matchTemplate` to locate each template image within the source image. Supports multiple templates in a single call — each template is matched independently. Returns matching locations above the threshold for each template, sorted by score (descending). Non-maximum suppression (NMS) is applied to remove duplicate matches.

## Returns
```json
{
  "success": true,
  "image": "ws:uploads/screenshot_001.png",
  "results": {
    "ws:uploads/button_a.png": {
      "matched": true,
      "match_count": 2,
      "matches": [
        {"x": 100, "y": 200, "w": 50, "h": 30, "score": 0.95},
        {"x": 300, "y": 200, "w": 50, "h": 30, "score": 0.85}
      ],
      "best": {"x": 100, "y": 200, "w": 50, "h": 30, "score": 0.95}
    },
    "ws:uploads/button_b.png": {
      "matched": false,
      "match_count": 0,
      "matches": [],
      "best": null
    }
  },
  "summary": {"total": 2, "matched": 1, "unmatched": 1},
  "threshold": 0.7,
  "roi": null,
  "method": 5
}
```
`x, y` is the top-left corner of the match in the original image coordinate system. `w, h` is the template dimensions. `score` is the match confidence (0-1, higher is better).

When a template's `matched` is false, its `matches` is empty and `best` is null. If a template file could not be read, an `error` field is included instead.

## When to Use
- After `screen_capture` to locate UI elements (buttons, icons, text regions) on screen.
- To find coordinates for `mouse_click` — use the `best` match's center: `x + w/2`, `y + h/2`.
- To match multiple UI elements in a single call — pass multiple template paths.
- To verify whether a specific UI state is present.

## ROI (Region of Interest)
Optional `roi` parameter limits the search area to `[x, y, w, h]` within the source image. This applies to all templates uniformly. Speeds up matching and reduces false positives. Returned coordinates are in the original image's coordinate system.

## Side Effects / Notes
- Read-only operation — does not modify any files.
- Requires `opencv-python` and `numpy` installed.
- Default matching method is `TM_CCOEFF_NORMED` (method=5), which is illumination-invariant and recommended by MAA.
- NMS overlap threshold is 0.5 — matches overlapping by more than 50% are deduplicated.
- `threshold`, `roi`, and `method` apply uniformly to all templates.""",
        "parameters": {
            "type": "object",
            "properties": {
                "image": {
                    "type": "string",
                    # 源图片的沙箱路径（ws: 命名空间，如 ws:uploads/screenshot_001.png）。
                    "description": "Sandbox path of the source image to search in (ws: namespace, e.g. 'ws:uploads/screenshot_001.png').",
                },
                "template_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    # 模板图片的沙箱路径列表（ws: 命名空间），支持多模板批量匹配。
                    "description": "Sandbox paths of template images to search for (ws: namespace). Supports multiple templates for batch matching.",
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
                    # 感兴趣区域 [x, y, w, h]，限定源图内的搜索范围，加速匹配并减少误匹配，默认全图。
                    "description": "Region of interest [x, y, w, h] to limit the search area within the source image. Default: full image.",
                },
                "method": {
                    "type": "integer",
                    # OpenCV 模板匹配方法，默认 5（TM_CCOEFF_NORMED），详见 cv2.TemplateMatchModes 文档。
                    "description": "OpenCV template matching method. Default: 5 (TM_CCOEFF_NORMED). See cv2.TemplateMatchModes docs.",
                    "default": 5,
                },
            },
            "required": ["image", "template_paths"],
        },
    },
    handler=_handle_template_match,
    check_fn=_check_cv2,
    emoji="🎯",
)