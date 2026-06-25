"""Excalidraw diagram generation tool.

Takes Excalidraw JSON (as a ws: file path or raw string), renders it to
PNG via Playwright, and returns a Markdown image URL for the frontend.

Usage:
  1. Write your Excalidraw JSON to a file: write_file(path="ws:diagrams/my.excalidraw", content="...")
  2. Call draw_diagram(json_file="ws:diagrams/my.excalidraw")
  3. The tool returns ![diagram](/uploads/diagrams/my.png) -- frontend renders it inline

Module-import-time registration via ``registry.register()``.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict

from abstract.tools.registry import registry, tool_error, tool_result
from .excalidraw_render import render, validate_excalidraw

from system.pathutils import get_templates_dir
from component.tools.filesystem import _s as _get_sandbox

logger = logging.getLogger(__name__)

# Path to the vendored HTML render template
template_html = get_templates_dir() / "html" / "excalidraw_template.html"

if TYPE_CHECKING:
    from component.tools.filesystem import Sandbox


def _check_dependencies() -> str | None:
    """Return None if OK, or an error message if Playwright is missing."""
    try:
        import playwright  # noqa: F401
        return None
    except ImportError:
        return (
            "需要安装 excalidraw 渲染依赖:\n"
            "  pip install playwright\n"
            "  python -m playwright install chromium"
        )


def _resolve_ws_path(path: str) -> tuple[Path, Path | None]:
    """Resolve a ws: path to a real filesystem path.

    Returns (real_fs_path, agentspace_base_or_None).
    If sandbox is not available, falls back to stripping 'ws:' prefix
    and using cwd as the base.
    """
    sb = _get_sandbox()
    if sb is not None:
        try:
            resolved = sb.resolve_read(path)
            agentspace = sb._ctx.agentspace
            return resolved.real, agentspace
        except Exception:
            pass

    # Fallback: strip ws: prefix, use cwd
    if path.startswith("ws:"):
        rel = path[3:].lstrip("/\\")
        return Path.cwd() / rel, None
    return Path(path), None


def _resolve_ws_dir_for_write(path: str) -> tuple[Path, Path | None]:
    """Resolve a ws: directory for writing output files.

    Similar to _resolve_ws_path but for determining where to save
    output files. Returns (output_dir, agentspace_base).
    """
    sb = _get_sandbox()
    if sb is not None:
        try:
            agentspace = sb._ctx.agentspace
            if path.startswith("ws:"):
                rel = path[3:].lstrip("/\\")
                return agentspace / rel, agentspace
        except Exception:
            pass

    if path.startswith("ws:"):
        rel = path[3:].lstrip("/\\")
        return Path.cwd() / rel, None
    return Path(path), None


def _compute_http_url(real_path: Path, agentspace_base: Path | None) -> str:
    """Compute the /uploads/ HTTP URL from a real filesystem path.

    If agentspace_base is known, the URL is relative to it.
    Otherwise, use the last 3 path components as a best-effort guess.
    """
    if agentspace_base and agentspace_base in real_path.parents:
        try:
            rel = real_path.relative_to(agentspace_base)
            return f"/uploads/{rel.as_posix()}"
        except ValueError:
            pass
    # Best-effort fallback: just use the filename
    return f"/uploads/{real_path.name}"


def _handle_draw_diagram(args: dict[str, Any]) -> dict:
    """Render Excalidraw JSON and return a Markdown image link.

    Two input modes:
      - json_file (preferred): ws: path to a .excalidraw JSON file
      - json (fallback): raw Excalidraw JSON string
    """
    dep_err = _check_dependencies()
    if dep_err:
        return tool_error(dep_err)

    json_file: str = str(args.get("json_file", "")).strip()
    json_str: str = str(args.get("json", "")).strip()

    if not json_file and not json_str:
        return tool_error(
            "Must provide json_file (ws: path) or json (raw JSON string).\n"
            "Recommended: save JSON with write_file first, then pass json_file parameter."
        )

    data: dict | None = None
    source_label: str = ""
    output_parent: Path = None # type: ignore
    agentspace_base: Path | None = None

    # --- Mode 1: load from file ---
    if json_file:
        try:
            fs_path, agentspace_base = _resolve_ws_path(json_file)
            if not fs_path.exists():
                return tool_error(
                    f"File not found: {json_file}\n"
                    f"Please write JSON first: write_file(path=\"{json_file}\", content=...)."
                )
            json_str = fs_path.read_text(encoding="utf-8")
            data = json.loads(json_str)
            output_parent = fs_path.parent
            source_label = json_file
        except Exception as exc:
            return tool_error(f"Failed to read file ({json_file}): {exc}")

    # --- Mode 2: inline JSON string ---
    if data is None and json_str:
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            return tool_error(f"JSON format error: {e}")
        # Determine output dir
        output_parent, agentspace_base = _resolve_ws_dir_for_write("ws:diagrams")
        source_label = "inline JSON"

    if data is None:
        return tool_error("无法解析 JSON 输入")

    # Validate
    errors = validate_excalidraw(data)
    if errors:
        return tool_error("Excalidraw JSON 校验失败:\n" + "\n".join(f"  - {e}" for e in errors))

    element_count = len([e for e in data.get("elements", []) if not e.get("isDeleted")])

    # Determine output paths
    output_parent.mkdir(parents=True, exist_ok=True)
    diagram_id = uuid.uuid4().hex[:12]
    png_name = f"{diagram_id}.png"
    json_name = f"{diagram_id}.excalidraw"
    png_path = output_parent / png_name
    json_path = output_parent / json_name

    # Write the JSON for reference
    try:
        json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write reference JSON: %s", exc)

    # Render to PNG
    try:
        render(excalidraw_json=json.dumps(data, ensure_ascii=False),
               output_png=png_path,
               template_html=template_html)
    except RuntimeError as exc:
        return tool_error(str(exc))

    # Compute HTTP URL
    http_url = _compute_http_url(png_path, agentspace_base)

    # Compute ws: logical path for tool result
    if agentspace_base:
        try:
            rel_path = output_parent.relative_to(agentspace_base)
            png_logical = f"ws:{rel_path.as_posix()}/{png_name}"
            json_logical = f"ws:{rel_path.as_posix()}/{json_name}"
        except ValueError:
            png_logical = f"ws:{output_parent.name}/{png_name}"
            json_logical = f"ws:{output_parent.name}/{json_name}"
    else:
        png_logical = f"ws:{output_parent.name}/{png_name}"
        json_logical = f"ws:{output_parent.name}/{json_name}"

    return tool_result(
        elements=element_count,
        source=source_label,
        json_path=json_logical,
        png_path=png_logical,
        markdown=http_url,
        message=f"diagram generated (with {element_count} elements)\n\n![]({http_url})",
    )


def _handle_render_diagram(args: dict[str, Any]) -> dict:
    """Render pre-existing Excalidraw JSON from a ws: path to PNG."""
    dep_err = _check_dependencies()
    if dep_err:
        return tool_error(dep_err)

    path: str = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required — .excalidraw file under ws: path")

    fs_path, agentspace_base = _resolve_ws_path(path)
    if not fs_path.exists():
        return tool_error(f"file not found: {path}")

    try:
        json_str = fs_path.read_text(encoding="utf-8")
    except OSError as exc:
        return tool_error(f"failed to read file: {exc}")

    data = json.loads(json_str)
    errors = validate_excalidraw(data)
    if errors:
        return tool_error("Excalidraw JSON validation failed:\n" + "\n".join(f"  - {e}" for e in errors))

    # Output in same directory as input
    output_parent = fs_path.parent
    output_parent.mkdir(parents=True, exist_ok=True)
    diagram_id = uuid.uuid4().hex[:12]
    png_name = f"{diagram_id}.png"
    png_path = output_parent / png_name

    try:
        render(excalidraw_json=json_str,
               output_png=png_path,
               template_html=template_html)
    except RuntimeError as exc:
        return tool_error(str(exc))

    http_url = _compute_http_url(png_path, agentspace_base)

    # Compute ws: logical path for tool result
    if agentspace_base:
        try:
            rel_path = output_parent.relative_to(agentspace_base)
            png_logical = f"ws:{rel_path.as_posix()}/{png_name}"
        except ValueError:
            png_logical = f"ws:{output_parent.name}/{png_name}"
    else:
        png_logical = f"ws:{output_parent.name}/{png_name}"

    return tool_result(
        source=path,
        png_path=png_logical,
        markdown=http_url,
        message=f"Diagram rendered\n\n![]({http_url})",
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

registry.register(
    name="draw_diagram",
    toolset="diagram",
    schema={
        # 将 Excalidraw JSON 渲染为 PNG 图片并返回 Markdown 图片链接。
        #
        # ## 前置条件
        # 必须安装 Playwright 和 Chromium（pip install playwright && python -m playwright install chromium）。
        # 推荐先用 write_file 将 Excalidraw JSON 保存到 ws: 路径，再传入 json_file 参数。
        # json_file 与 json 参数互斥。
        #
        # ## 调用效果
        # 解析 Excalidraw JSON，渲染为 PNG，保存到 ws:diagrams/。
        # 返回 PNG 路径、Markdown 链接以及参考的 .excalidraw 文件路径。
        #
        # ## 返回
        # ```json
        # {"elements": 10, "source": "ws:diagrams/my.excalidraw", "json_path": "ws:diagrams/xxx.excalidraw", "png_path": "ws:diagrams/xxx.png", "markdown": "/uploads/diagrams/xxx.png", "message": "..."}
        # ```
        #
        # ## 何时使用
        # - 从 Excalidraw JSON 生成手绘风格图表。
        # - 向用户展示流程图、架构图等可视化内容。
        #
        # ## 副作用/注意
        # - 会写入 PNG 和 .excalidraw 文件到工作空间。
        # - 首次加载 CDN 资源可能较慢。
        "description": """Render Excalidraw JSON to a PNG image and return a Markdown image link.

## Prerequisites
Playwright and Chromium must be installed (pip install playwright && python -m playwright install chromium). It is recommended to save the Excalidraw JSON to a ws: path with write_file first, then pass the json_file parameter. json_file and json are mutually exclusive.

## Effect
Parses the Excalidraw JSON, renders it to a PNG, and saves it under ws:diagrams/. Returns the PNG path, Markdown link, and the reference .excalidraw file path.

## Returns
```json
{"elements": 10, "source": "ws:diagrams/my.excalidraw", "json_path": "ws:diagrams/xxx.excalidraw", "png_path": "ws:diagrams/xxx.png", "markdown": "/uploads/diagrams/xxx.png", "message": "..."}
```

## When to Use
- Generate hand-drawn style diagrams from Excalidraw JSON.
- Display flowcharts, architecture diagrams, or other visuals to the user.

## Side Effects / Notes
- Writes PNG and .excalidraw files to the workspace.
- First-time CDN loading can be slow.""",
        "parameters": {
            "type": "object",
            "properties": {
                "json_file": {
                    "type": "string",
                    # ws: 前缀下的 .excalidraw JSON 文件路径。推荐先用 write_file 保存 JSON 到此路径。
                    "description": """Path to .excalidraw JSON file under ws: prefix. Save JSON to this path with write_file first. Example: ws:diagrams/mindmap.excalidraw.""",
                },
                "json": {
                    "type": "string",
                    # 完整的 Excalidraw JSON 字符串（备选方案）。仅在图表很小、可直接构造时使用。
                    "description": """Full Excalidraw JSON string (fallback). Only use for small diagrams constructable inline.""",
                },
            },
        },
    },
    handler=_handle_draw_diagram,
    emoji="📊",
)

registry.register(
    name="render_diagram",
    toolset="diagram",
    schema={
        # 重新渲染工作区中已有的 .excalidraw JSON 文件为 PNG。
        #
        # ## 前置条件
        # 必须安装 Playwright 和 Chromium。
        # path 必须指向一个已存在的 ws: 路径下的 .excalidraw 文件。
        #
        # ## 调用效果
        # 读取已有的 .excalidraw 文件，渲染为 PNG 并保存到同一目录。
        # 返回 PNG 路径和 Markdown 链接。
        #
        # ## 返回
        # ```json
        # {"source": "ws:diagrams/my.excalidraw", "png_path": "ws:diagrams/xxx.png", "markdown": "/uploads/diagrams/xxx.png", "message": "..."}
        # ```
        #
        # ## 何时使用
        # - 修改 Excalidraw JSON 后重新生成图片。
        # - 迭代编辑图表并多次渲染。
        #
        # ## 副作用/注意
        # - 会写入新的 PNG 文件到工作空间。
        # - 不会修改原始 .excalidraw 文件。
        "description": """Re-render an existing .excalidraw JSON file in the workspace to PNG.

## Prerequisites
Playwright and Chromium must be installed. path must point to an existing .excalidraw file under the ws: namespace.

## Effect
Reads the existing .excalidraw file, renders it to a PNG, and saves the PNG in the same directory. Returns the PNG path and Markdown link.

## Returns
```json
{"source": "ws:diagrams/my.excalidraw", "png_path": "ws:diagrams/xxx.png", "markdown": "/uploads/diagrams/xxx.png", "message": "..."}
```

## When to Use
- Regenerate the image after modifying Excalidraw JSON.
- Iteratively edit and re-render diagrams.

## Side Effects / Notes
- Writes a new PNG file to the workspace.
- Does not modify the original .excalidraw file.""",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # ws: 前缀下的 .excalidraw 文件路径（如 ws:diagrams/mydiagram.excalidraw）。
                    "description": """Path to .excalidraw file under ws: prefix (e.g. ws:diagrams/mydiagram.excalidraw).""",
                },
            },
            "required": ["path"],
        },
    },
    handler=_handle_render_diagram,
    emoji="🔄",
)