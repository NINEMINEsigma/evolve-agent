"""PDF 工具 — 读取 .pdf 文件中的文本内容。

模块导入时通过 ``registry.register()`` 注册。
依赖 ``pypdf``（请参见 requirements.txt）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from abstract.tools.registry import registry, tool_error, tool_result
from component.tools.filesystem import _s as _get_sandbox

logger = logging.getLogger(__name__)

_pypdf = None
try:
    import pypdf as _pypdf
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def _handle_read_pdf(args: Dict[str, Any]) -> str:
    path: str = str(args.get("path", "")).strip()
    if not path:
        return tool_error("path is required")

    if _pypdf is None:
        return tool_error(
            "pypdf is not installed. Run: pip install pypdf",
        )

    try:
        sandbox = _get_sandbox()
        r = sandbox.resolve_read(path)
    except Exception as e:
        return tool_error(str(e), path=path)

    try:
        reader = _pypdf.PdfReader(str(r.real))
    except Exception as e:
        return tool_error(f"Failed to open PDF: {e}", path=path)

    total_pages: int = len(reader.pages)

    # 页范围：默认全部；支持 "1-based" 页数
    start_page: int = int(args.get("start_page", 1))
    end_page: int = int(args.get("end_page", total_pages))

    if start_page < 1:
        start_page = 1
    if end_page > total_pages:
        end_page = total_pages
    if start_page > end_page:
        return tool_error(
            f"start_page ({start_page}) must be <= end_page ({end_page})",
            path=path, total_pages=total_pages,
        )

    pages: list[dict[str, Any]] = []
    plain_text_parts: list[str] = []

    for i in range(start_page - 1, end_page):
        try:
            page = reader.pages[i]
            text: str = (page.extract_text() or "").strip()
            pages.append({
                "page_number": i + 1,
                "text": text,
                "char_count": len(text),
            })
            plain_text_parts.append(f"--- Page {i + 1} ---\n{text}")
        except Exception as e:
            pages.append({
                "page_number": i + 1,
                "text": "",
                "error": str(e),
            })

    return tool_result(
        path=path,
        pages=pages,
        total_pages=total_pages,
        page_range=f"{start_page}-{end_page}",
        plain_text="\n\n".join(plain_text_parts),
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

registry.register(
    name="read_pdf",
    toolset="extools",
    schema={
        "description": (
            "读取 .pdf 文件并提取文本内容。返回每页的文本和全文拼接。"
            "支持指定页范围（start_page / end_page，从 1 开始计数）。"
            "适用于文档阅读、报告分析、信息提取等场景。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "PDF 文件逻辑路径，必须使用命名空间前缀 "
                        "（ws:、fork:）。例如 'ws:docs/report.pdf'。"
                    ),
                },
                "start_page": {
                    "type": "integer",
                    "description": "起始页码（从 1 开始，默认 1）。",
                    "default": 1,
                },
                "end_page": {
                    "type": "integer",
                    "description": "结束页码（默认到最后一页）。",
                },
            },
            "required": ["path"],
        },
    },
    handler=_handle_read_pdf,
    emoji="📕",
)