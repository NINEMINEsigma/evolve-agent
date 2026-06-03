"""Render Excalidraw JSON to PNG using Playwright + headless Chromium.

Vendored and adapted from the excalidraw-diagram skill.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def validate_excalidraw(data: dict) -> list[str]:
    """Validate Excalidraw JSON structure. Returns list of errors (empty = valid)."""
    errors: list[str] = []
    if data.get("type") != "excalidraw":
        errors.append(f"Expected type 'excalidraw', got '{data.get('type')}'")
    if "elements" not in data:
        errors.append("Missing 'elements' array")
    elif not isinstance(data["elements"], list):
        errors.append("'elements' must be an array")
    elif len(data["elements"]) == 0:
        errors.append("'elements' array is empty")
    return errors


def compute_bounding_box(elements: list[dict]) -> tuple[float, float, float, float]:
    """Compute bounding box (min_x, min_y, max_x, max_y) across all elements."""
    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")
    for el in elements:
        if el.get("isDeleted"):
            continue
        x = el.get("x", 0)
        y = el.get("y", 0)
        w = el.get("width", 0)
        h = el.get("height", 0)
        if el.get("type") in ("arrow", "line") and "points" in el:
            for px, py in el["points"]:
                min_x = min(min_x, x + px)
                min_y = min(min_y, y + py)
                max_x = max(max_x, x + px)
                max_y = max(max_y, y + py)
        else:
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x + abs(w))
            max_y = max(max_y, y + abs(h))
    if min_x == float("inf"):
        return (0, 0, 800, 600)
    return (min_x, min_y, max_x, max_y)


def render(
    excalidraw_json: str,
    output_png: Path,
    template_html: Path,
    scale: int = 2,
    max_width: int = 1920,
) -> None:
    """Render Excalidraw JSON string to PNG.

    Raises RuntimeError on failure.
    """
    try:
        data = json.loads(excalidraw_json)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON: {e}")

    errors = validate_excalidraw(data)
    if errors:
        raise RuntimeError("Invalid Excalidraw data: " + "; ".join(errors))

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "playwright library is required:\n"
            "  pip install playwright\n"
            "  python -m playwright install chromium"
        )

    elements = [e for e in data["elements"] if not e.get("isDeleted")]
    min_x, min_y, max_x, max_y = compute_bounding_box(elements)
    padding = 80
    diagram_w = max_x - min_x + padding * 2
    diagram_h = max_y - min_y + padding * 2
    vp_width = min(int(diagram_w), max_width)
    vp_height = max(int(diagram_h), 600)

    if not template_html.exists():
        raise RuntimeError(f"Render template not found: {template_html}")

    template_url = template_html.as_uri()

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as e:
            if "Executable doesn't exist" in str(e):
                raise RuntimeError(
                    "Chromium is not installed:\n"
                    "  python -m playwright install chromium"
                )
            raise RuntimeError(f"Browser launch failed: {e}")

        page = browser.new_page(
            viewport={"width": vp_width, "height": vp_height},
            device_scale_factor=scale,
        )

        # Navigate and wait for the Excalidraw module to load from CDN.
        # First load can be slow (esm.sh bundle download).
        page.goto(template_url)
        try:
            page.wait_for_function(
                "window.__moduleReady === true",
                timeout=120_000,
            )
        except Exception as exc:
            browser.close()
            raise RuntimeError(f"Excalidraw module load timed out (120s): {exc}")

        # Evaluate the render function
        result = page.evaluate(f"window.renderDiagram({json.dumps(data)})")
        if not result or not result.get("success"):
            err = result.get("error", "unknown error") if result else "renderDiagram returned null"
            browser.close()
            raise RuntimeError(f"Render failed: {err}")

        # Wait for the SVG to be fully rendered. Complex diagrams with many
        # elements may take significant time.
        try:
            page.wait_for_function(
                "window.__renderComplete === true",
                timeout=120_000,
            )
        except Exception as exc:
            # Capture partial state for debugging
            has_svg = page.query_selector("#root svg") is not None
            err_info = f"Render wait timed out (120s), SVG generated={has_svg}"
            if not has_svg:
                # Check for any JS errors
                logs = page.evaluate("() => window.__renderError || null")
                if logs:
                    err_info += f", 错误: {logs}"
            browser.close()
            raise RuntimeError(err_info)
        svg_el = page.query_selector("#root svg")
        if svg_el is None:
            browser.close()
            raise RuntimeError("未找到渲染后的 SVG 元素")
        svg_el.screenshot(path=str(output_png))
        browser.close()