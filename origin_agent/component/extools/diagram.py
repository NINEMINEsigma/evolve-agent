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
from typing import Any, Dict

from abstract.tools.registry import registry, tool_error, tool_result

from .excalidraw_render import render, validate_excalidraw

logger = logging.getLogger(__name__)

# Path to the vendored HTML render template (same directory as this file)
_TEMPLATE_DIR = Path(__file__).resolve().parent

# Lazy import of Sandbox (set at runtime by main.py)
_fs_sandbox: Any | None = None


def _get_sandbox():
    """Lazy import of the shared Sandbox from filesystem tools."""
    global _fs_sandbox
    if _fs_sandbox is None:
        from component.tools.filesystem import _sandbox
        _fs_sandbox = _sandbox
    return _fs_sandbox


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


def _handle_draw_diagram(args: Dict[str, Any]) -> str:
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
            "需要提供 json_file（ws: 路径）或 json（原始 JSON 字符串）。\n"
            "推荐方式: 先用 write_file 保存 JSON，再传入 json_file 参数。"
        )

    data: dict | None = None
    source_label: str = ""
    output_parent: Path | None = None
    agentspace_base: Path | None = None

    # --- Mode 1: load from file ---
    if json_file:
        try:
            fs_path, agentspace_base = _resolve_ws_path(json_file)
            if not fs_path.exists():
                return tool_error(
                    f"文件不存在: {json_file}\n"
                    f"请先用 write_file(path=\"{json_file}\", content=...) 写入 JSON。"
                )
            json_str = fs_path.read_text(encoding="utf-8")
            data = json.loads(json_str)
            output_parent = fs_path.parent
            source_label = json_file
        except Exception as exc:
            return tool_error(f"读取文件失败 ({json_file}): {exc}")

    # --- Mode 2: inline JSON string ---
    if data is None and json_str:
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            return tool_error(f"JSON 格式错误: {e}")
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
    template_html = _TEMPLATE_DIR / "excalidraw_template.html"
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
        message=f"图表已生成（{element_count} 个元素）\n\n![]({http_url})",
    )


def _handle_render_diagram(args: Dict[str, Any]) -> str:
    """Render pre-existing Excalidraw JSON from a ws: path to PNG."""
    dep_err = _check_dependencies()
    if dep_err:
        return tool_error(dep_err)

    path: str = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path 是必填的 — ws: 路径下的 .excalidraw 文件")

    fs_path, agentspace_base = _resolve_ws_path(path)
    if not fs_path.exists():
        return tool_error(f"文件不存在: {path}")

    try:
        json_str = fs_path.read_text(encoding="utf-8")
    except OSError as exc:
        return tool_error(f"读取文件失败: {exc}")

    data = json.loads(json_str)
    errors = validate_excalidraw(data)
    if errors:
        return tool_error("Excalidraw JSON 校验失败:\n" + "\n".join(f"  - {e}" for e in errors))

    # Output in same directory as input
    output_parent = fs_path.parent
    output_parent.mkdir(parents=True, exist_ok=True)
    diagram_id = uuid.uuid4().hex[:12]
    png_name = f"{diagram_id}.png"
    png_path = output_parent / png_name

    template_html = _TEMPLATE_DIR / "excalidraw_template.html"
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
        message=f"图表已渲染\n\n![]({http_url})",
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

registry.register(
    name="draw_diagram",
    toolset="diagram",
    schema={
        "description": (
            "将 Excalidraw JSON 渲染为 PNG 图片，返回 Markdown 图片链接。\n\n"
            "使用步骤:\n"
            "  1. 用 write_file 将 Excalidraw JSON 保存到文件，如 "
            "write_file(path='ws:diagrams/my.excalidraw', content='...')\n"
            "  2. 调用 draw_diagram(json_file='ws:diagrams/my.excalidraw')\n"
            "  3. 工具返回 ![diagram](/uploads/diagrams/xxx.png)，前端自动显示\n\n"
            "Excalidraw JSON 格式:\n"
            '  { "type": "excalidraw", "version": 2, '
            '"elements": [...], "appState": {...} }\n\n'
            "元素类型: rectangle, text, arrow, ellipse, diamond, line 等\n"
            "每个元素需要 id, type, x, y, width, height, strokeColor, backgroundColor 等字段\n"
            "文本元素有 text, fontSize, fontFamily(1=手写, 2=正常, 3=代码), "
            "textAlign, verticalAlign\n"
            "箭头用 points: [[x1,y1], [x2,y2]] 定义路径\n\n"
            "使用前需安装: pip install playwright && python -m playwright install chromium\n"
            "agent 应通过 JSON 结构完整性来判断正确性，用户通过前端查看渲染结果。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "json_file": {
                    "type": "string",
                    "description": (
                        "ws: 前缀下的 .excalidraw JSON 文件路径。"
                        "先用 write_file 保存 JSON 到此路径，再传入。"
                        "例如: ws:diagrams/mindmap.excalidraw"
                    ),
                },
                "json": {
                    "type": "string",
                    "description": (
                        "完整的 Excalidraw JSON 字符串（备选方案）。"
                        "仅在图表很小、可直接构造时使用。"
                        "复杂图表请使用 json_file 参数。"
                    ),
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
        "description": (
            "将 workspace 中已有的 .excalidraw JSON 文件重新渲染为 PNG。"
            "用于迭代修改后重新生成图片。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "ws: 前缀下的 .excalidraw 文件路径（如 ws:diagrams/mydiagram.excalidraw）。",
                },
            },
            "required": ["path"],
        },
    },
    handler=_handle_render_diagram,
    emoji="🔄",
)