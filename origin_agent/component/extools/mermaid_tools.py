"""Mermaid diagram rendering tool.

Renders Mermaid definition strings to PNG images using Playwright +
headless Chromium, and returns a Markdown image URL for the frontend.

Usage:
  1. ``draw_mermaid(definition="graph TD; A-->B;")``
  2. Returns ``![diagram](/uploads/diagrams/xxx.png)`` — frontend renders it inline

Module-import-time registration via ``registry.register()``.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict

from abstract.tools.registry import registry, tool_error, tool_result
from system.pathutils import get_templates_dir

logger = logging.getLogger(__name__)


def render(
    mermaid_definition: str,
    output_png: Path,
    template_html: Path,
    theme: str = "default",
    scale: int = 2,
    max_width: int = 1920,
) -> None:
    """Render a Mermaid definition string to a PNG image.

    Args:
        mermaid_definition: Raw Mermaid syntax string (e.g. ``graph TD; A-->B;``).
        output_png: Destination path for the generated PNG.
        template_html: Path to ``mermaid_template.html``.
        theme: Mermaid theme name (default, forest, dark, neutral).
        scale: Device pixel ratio for high-DPI output.
        max_width: Maximum viewport width in pixels.

    Raises:
        RuntimeError: If Playwright is unavailable, the CDN fails to load,
            or rendering fails for any reason.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "playwright library is required:\n"
            "  pip install playwright\n"
            "  python -m playwright install chromium"
        )

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
            viewport={"width": max_width, "height": 800},
            device_scale_factor=scale,
        )

        page.goto(template_url)

        # Wait for Mermaid library to load from CDN
        try:
            page.wait_for_function(
                "typeof mermaid !== 'undefined'",
                timeout=120_000,
            )
        except Exception as exc:
            browser.close()
            raise RuntimeError(f"Mermaid library load timed out (120s): {exc}")

        # Call the render function
        escaped_def = json.dumps(mermaid_definition)
        result = page.evaluate(
            f"window.renderMermaid({escaped_def}, {json.dumps(theme)})"
        )
        if not result or not result.get("success"):
            err = result.get("error", "unknown error") if result else "renderMermaid returned null"
            browser.close()
            raise RuntimeError(f"Mermaid render failed: {err}")

        # Wait for completion
        try:
            page.wait_for_function(
                "window.__mermaidReady === true",
                timeout=30_000,
            )
        except Exception as exc:
            err_info = "Mermaid render wait timed out (30s)"
            error_msg = page.evaluate("window.__mermaidError || null")
            if error_msg:
                err_info += f", error: {error_msg}"
            browser.close()
            raise RuntimeError(err_info)

        # Check for render-phase error
        error_msg = page.evaluate("window.__mermaidError || null")
        if error_msg:
            browser.close()
            raise RuntimeError(f"Mermaid render error: {error_msg}")

        # Screenshot the SVG element
        svg_el = page.query_selector("#root svg")
        if svg_el is None:
            browser.close()
            raise RuntimeError("No SVG element found after Mermaid render")
        svg_el.screenshot(path=str(output_png))
        browser.close()


# Path to the vendored HTML render template
template_html = get_templates_dir() / "html" / "mermaid_template.html"

if TYPE_CHECKING:
    from component.tools.filesystem import Sandbox

# Lazy import of Sandbox (set at runtime by main.py)
_fs_sandbox: Sandbox | None = None


def _get_sandbox() -> Sandbox:
    """Lazy import of the shared Sandbox from filesystem tools."""
    global _fs_sandbox
    if _fs_sandbox is None:
        from component.tools.filesystem import _sandbox
        _fs_sandbox = _sandbox
    return _fs_sandbox  # type: ignore


def _check_dependencies() -> str | None:
    """Return None if OK, or an error message if Playwright is missing."""
    try:
        import playwright  # noqa: F401
        return None
    except ImportError:
        return (
            "Playwright is required for Mermaid rendering:\n"
            "  pip install playwright\n"
            "  python -m playwright install chromium"
        )


def _resolve_ws_path(path: str) -> tuple[Path, Path | None]:
    """Resolve a ws: path to a real filesystem path.

    Returns (real_fs_path, agentspace_base_or_None).
    """
    sb = _get_sandbox()
    if sb is not None:
        try:
            resolved = sb.resolve_read(path)
            agentspace = sb._ctx.agentspace
            return resolved.real, agentspace
        except Exception:
            pass
    # Fallback
    if path.startswith("ws:"):
        rel = path[3:].lstrip("/\\")
        return Path.cwd() / rel, None
    return Path(path), None


def _resolve_ws_dir_for_write(path: str) -> tuple[Path, Path | None]:
    """Resolve a ws: directory for writing output files. Returns (output_dir, agentspace_base)."""
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
    """Compute the /uploads/ HTTP URL from a real filesystem path."""
    if agentspace_base and agentspace_base in real_path.parents:
        try:
            rel = real_path.relative_to(agentspace_base)
            return f"/uploads/{rel.as_posix()}"
        except ValueError:
            pass
    return f"/uploads/{real_path.name}"


# ── Tool handler ──────────────────────────────────────────────────────────


def _handle_draw_mermaid(args: Dict[str, Any]) -> str:
    """Render a Mermaid diagram to PNG and return a Markdown image link.

    Two input modes (mutually exclusive):
      - definition: inline Mermaid syntax string
      - file:       ws: path to a .mmd file
    """
    dep_err = _check_dependencies()
    if dep_err:
        return tool_error(dep_err)

    definition: str = str(args.get("definition", "")).strip()
    file_path: str = str(args.get("file", "")).strip()
    theme: str = str(args.get("theme", "default")).strip()

    valid_themes = {"default", "forest", "dark", "neutral"}
    if theme not in valid_themes:
        return tool_error(
            f"Invalid theme '{theme}'. Must be one of: {', '.join(sorted(valid_themes))}."
        )

    if not definition and not file_path:
        return tool_error(
            "Must provide 'definition' (inline Mermaid string) or 'file' (ws: path to .mmd file)."
        )
    if definition and file_path:
        return tool_error("Provide only one of 'definition' or 'file', not both.")

    resolved_definition: str = ""
    output_parent: Path | None = None
    agentspace_base: Path | None = None
    source_label: str = ""

    # ── Mode 1: load from file ──
    if file_path:
        try:
            fs_path, agentspace_base = _resolve_ws_path(file_path)
            if not fs_path.exists():
                return tool_error(
                    f"File not found: {file_path}\n"
                    f"Write the file first: write_file(path=\"{file_path}\", content=\"...\")."
                )
            resolved_definition = fs_path.read_text(encoding="utf-8")
            output_parent = fs_path.parent
            source_label = file_path
        except Exception as exc:
            return tool_error(f"Failed to read file ({file_path}): {exc}")

    # ── Mode 2: inline definition ──
    if not resolved_definition:
        resolved_definition = definition
        output_parent, agentspace_base = _resolve_ws_dir_for_write("ws:diagrams")
        source_label = "inline definition"

    if not resolved_definition.strip():
        return tool_error("Mermaid definition is empty.")

    # ── Render ──
    output_parent.mkdir(parents=True, exist_ok=True)
    diagram_id = uuid.uuid4().hex[:12]
    png_name = f"{diagram_id}.png"
    png_path = output_parent / png_name

    try:
        render(
            mermaid_definition=resolved_definition,
            output_png=png_path,
            template_html=template_html,
            theme=theme,
        )
    except RuntimeError as exc:
        return tool_error(str(exc))

    # ── Compute URLs ──
    http_url = _compute_http_url(png_path, agentspace_base)

    if agentspace_base:
        try:
            rel_path = output_parent.relative_to(agentspace_base)
            png_logical = f"ws:{rel_path.as_posix()}/{png_name}"
        except ValueError:
            png_logical = f"ws:{output_parent.name}/{png_name}"
    else:
        png_logical = f"ws:{output_parent.name}/{png_name}"

    # Try to save the definition as .mmd alongside the PNG for reference
    try:
        mmd_path = output_parent / f"{diagram_id}.mmd"
        mmd_path.write_text(resolved_definition, encoding="utf-8")
        if agentspace_base:
            try:
                rel_path = output_parent.relative_to(agentspace_base)
                mmd_logical = f"ws:{rel_path.as_posix()}/{diagram_id}.mmd"
            except ValueError:
                mmd_logical = f"ws:{output_parent.name}/{diagram_id}.mmd"
        else:
            mmd_logical = f"ws:{output_parent.name}/{diagram_id}.mmd"
    except OSError as exc:
        logger.warning("Could not write reference .mmd file: %s", exc)
        mmd_logical = None

    return tool_result(
        source=source_label,
        theme=theme,
        png_path=png_logical,
        markdown=http_url,
        mmd_path=mmd_logical,
        message=f"Mermaid diagram rendered (theme: {theme})\n\n![]({http_url})",
    )


# ── Registration ──────────────────────────────────────────────────────────

registry.register(
    name="draw_mermaid",
    toolset="mermaid",
    schema={
        "description": (
            "Render a Mermaid diagram definition to a PNG image and return a "
            "Markdown image link.\n\n"
            "Mermaid is a diagramming and charting tool that renders Markdown-like "
            "text definitions to diagrams.\n\n"
            "Common diagram types (full syntax at https://mermaid.js.org/syntax/):\n"
            "  - graph TD; A-->B;  (flowchart, top-down)\n"
            "  - graph LR; A-->B;  (flowchart, left-right)\n"
            "  - sequenceDiagram; A->>B: Hello; (sequence)\n"
            "  - classDiagram; class Animal; (class)\n"
            "  - stateDiagram-v2; [*] --> Idle; (state)\n"
            "  - gantt; title Timeline; (gantt chart)\n"
            "  - pie; \"A\": 40; \"B\": 60; (pie chart)\n"
            "  - erDiagram; CUSTOMER ||--o{ ORDER : places; (ER diagram)\n\n"
            "Usage:\n"
            '  draw_mermaid(definition="graph TD; A-->B;")\n\n'
            "  Or save to a .mmd file first:\n"
            '  write_file(path="ws:diagrams/my.mmd", content="graph TD; A-->B;")\n'
            '  draw_mermaid(file="ws:diagrams/my.mmd")\n\n'
            "Supported themes: default, forest, dark, neutral\n\n"
            "Returns:\n"
            "  - png_path: ws: path to the generated PNG\n"
            "  - mmd_path: ws: path to the saved .mmd reference file\n"
            "  - markdown: image URL for frontend display\n"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "definition": {
                    "type": "string",
                    "description": (
                        "Inline Mermaid diagram definition string. "
                        "Mutually exclusive with 'file'.\n"
                        "Examples:\n"
                        '  "graph TD; A-->B;"\n'
                        '  "sequenceDiagram; Alice->>Bob: Hello;"'
                    ),
                },
                "file": {
                    "type": "string",
                    "description": (
                        "Path to a .mmd file under ws: prefix. "
                        "Mutually exclusive with 'definition'.\n"
                        "Example: ws:diagrams/my.mmd"
                    ),
                },
                "theme": {
                    "type": "string",
                    "enum": ["default", "forest", "dark", "neutral"],
                    "description": "Mermaid theme. Default: 'default'.",
                    "default": "default",
                },
            },
        },
    },
    handler=_handle_draw_mermaid,
    emoji="📊",
)