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


def _handle_read_pdf(args: dict[str, Any]) -> dict:
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
        # 读取 PDF 文件并提取每页文本内容。
        #
        # ## 前置条件
        # 必须安装 pypdf 库。
        # path 必须使用命名空间前缀（如 ws:、fork:）。
        #
        # ## 调用效果
        # 打开 PDF 文件，按页提取文本，返回每页文本、纯文本拼接、总页数等信息。
        # 支持通过 start_page 和 end_page 指定页码范围（1-based）。
        #
        # ## 返回
        # ```json
        # {"path": "ws:docs/report.pdf", "pages": [{"page_number": 1, "text": "...", "char_count": 100}], "total_pages": 10, "page_range": "1-10", "plain_text": "..."}
        # ```
        #
        # ## 何时使用
        # - 读取 PDF 报告、论文或文档内容。
        # - 从 PDF 中提取信息进行分析或摘要。
        #
        # ## 副作用/注意
        # - 纯文本提取依赖 pypdf，复杂排版可能丢失格式。
        # - 不会修改源文件。
        "description": """Read a .pdf file and extract text content per page.

## Prerequisites
The pypdf library must be installed. The path must use a namespace prefix (e.g. ws:, fork:).

## Effect
Opens the PDF file and extracts text page by page. Returns per-page text, a concatenated plain-text version, total pages, and other metadata. Supports page range selection via start_page and end_page (1-based).

## Returns
```json
{"path": "ws:docs/report.pdf", "pages": [{"page_number": 1, "text": "...", "char_count": 100}], "total_pages": 10, "page_range": "1-10", "plain_text": "..."}
```

## When to Use
- Read PDF reports, papers, or documents.
- Extract information from PDFs for analysis or summarization.

## Side Effects / Notes
- Plain text extraction relies on pypdf; complex layouts may lose formatting.
- Does not modify the source file.""",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # PDF 文件逻辑路径，必须使用命名空间前缀（ws:、fork:）。例如 'ws:docs/report.pdf'。
                    "description": """PDF file logical path, must use a namespace prefix (ws:, fork:). E.g. 'ws:docs/report.pdf'.""",
                },
                "start_page": {
                    "type": "integer",
                    # 起始页码（从 1 开始，默认 1）。
                    "description": """Start page number (1-based, default 1).""",
                    "default": 1,
                },
                "end_page": {
                    "type": "integer",
                    # 结束页码（默认到最后一页）。
                    "description": """End page number (defaults to last page).""",
                },
            },
            "required": ["path"],
        },
    },
    handler=_handle_read_pdf,
    emoji="📕",
)