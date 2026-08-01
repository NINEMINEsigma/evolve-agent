"""browser_read — 结构化读取页面元素（readonly）。

read 一个元素时返回两部分：
1. 本元素自身形态（不含子元素）：直接文本节点完整返回 + 原始 HTML 形态；
2. 下一层子节点列表（可过滤）：每个子元素仅带截断摘要与导航信号。

截断规则：本元素文本（self_text）永远完整不截断；子元素文本（children[].text）
永远只展示开头摘要——要读某子元素的完整内容，就对该子元素再发起 read。
模块导入时通过 ``registry.register()`` 注册。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from abstract.tools.registry import registry, tool_error, tool_result
from component.browser import _connection
from component.tools.filesystem import _s as _get_sandbox
from entity.constant import TOOL_RESULT_PREVIEW_CHARS, WEB_FETCH_MAX_CHARS
from entity.puretype import ToolDangerLevel

logger = logging.getLogger(__name__)

_NOT_CONNECTED: str = (
    "浏览器未连接或 CDP 端点不可达。请先调用 browser_connect；"
    "若 connect 曾返回指引，请先按指引让用户完成操作。"
)

_TAB_NOT_FOUND: str = (
    "未找到匹配的标签页。请先用 browser_list_tabs 确认现有标签页；"
    "若目标页面未在其中，请用户在浏览器中手动打开或切换到目标页面后重试。"
)


async def _handle_browser_read(args: dict[str, Any]) -> dict:
    tab: str = str(args.get("tab", "")).strip()
    path: str = str(args.get("path", "")).strip()
    selector: str = str(args.get("selector", "")).strip()
    filter_tag: str = str(args.get("filter_tag", "")).strip()
    filter_text: str = str(args.get("filter_text", "")).strip()
    mode: str = str(args.get("mode", "children")).strip().lower()
    detailed: bool = bool(args.get("detailed", False))

    if not tab:
        return tool_error("tab is required")
    if mode not in ("children", "text"):
        return tool_error("mode must be 'children' or 'text'")
    if not path and not selector:
        return tool_error("provide 'path' or 'selector' (at least one)")
    if path and selector:
        return tool_error("provide either 'path' or 'selector', not both")

    try:
        browser = await _connection.get_browser()
    except Exception as exc:
        logger.warning("browser_read: reconnect failed: %s: %s", type(exc).__name__, exc)
        return tool_error(_NOT_CONNECTED)

    page = await _connection.find_page(browser, tab)
    if page is None:
        return tool_error(_TAB_NOT_FOUND, tab=tab)

    try:
        title = await page.title()
    except Exception:
        title = ""

    if mode == "text":
        return await _read_text(page, path, selector, title)
    return await _read_children(page, path, selector, filter_tag, filter_text, title, detailed)


async def _read_text(page: Any, path: str, selector: str, title: str) -> dict:
    """text 模式：返回指定元素子树完整 innerText；超限落盘复用 web_fetch 契约。"""
    result = await _connection.dom_text(page, path=path, selector=selector)
    if "error" in result:
        return tool_error(
            result["error"] + "（若需确认目标元素，请先用 browser_query 定位）",
            path=path or None,
            selector=selector or None,
        )
    text: str = result.get("text", "")
    url: str = page.url or ""
    if len(text) > WEB_FETCH_MAX_CHARS:
        save_path = f"ws:logs/browser_text/{uuid.uuid4().hex[:12]}.txt"
        _get_sandbox().write(save_path, text)
        return tool_result(
            mode="text",
            preview=text[:TOOL_RESULT_PREVIEW_CHARS],
            saved_to=save_path,
            total_chars=len(text),
            tab_title=title,
            tab_url=url,
        )
    return tool_result(mode="text", text=text, tab_title=title, tab_url=url)


async def _read_children(
    page: Any,
    path: str,
    selector: str,
    filter_tag: str,
    filter_text: str,
    title: str,
    detailed: bool = False,
) -> dict:
    """children 模式（默认）：返回本元素自身形态 + 一层子节点摘要。

    *detailed* 为 True 时附加完整字段（href/src/style 原始值 + content textContent）。
    """
    result = await _connection.dom_snapshot(
        page,
        path=path,
        selector=selector,
        filter_tag=filter_tag,
        filter_text=filter_text,
        detailed=detailed,
    )
    if "error" in result:
        return tool_error(
            result["error"] + "（若需确认目标元素，请先用 browser_query 定位）",
            path=path or None,
            selector=selector or None,
        )
    return tool_result(
        element=result["element"],
        children=result["children"],
        total=result["total"],
        tab_title=title,
        tab_url=page.url or "",
    )


registry.register(
    name="browser_read",
    toolset="browser",
    schema={
        # 结构化读取页面元素：mode 决定返回形态。
        #
        # ## 前置条件
        # - 已成功调用 browser_connect；目标标签页存在；目标元素已定位
        #   （path 来自 browser_query 结果，或 selector 直接指定）。
        #
        # ## mode（必选其一语义）
        # - "children"（默认）：返回本元素自身形态 + 下一层子节点列表：
        #   1. element —— 本元素自身形态（**不含子元素**）：
        #      self_text（直接文本节点，完整不截断）、self_html（原始 HTML 形态，
        #      即克隆节点删除全部子元素后的 outerHTML）、leaf（无子元素）。
        #   2. children —— 下一层子元素列表，每项 {index, path, tag, id, class,
        #      text（子树文本摘要，截断）, child_count, leaf}。
        #   过滤（作用于 children，可组合）：filter_tag（tag 精确匹配）、
        #   filter_text（子树可见文本包含，含后代，大小写不敏感）。
        # - "text"：返回指定元素子树**完整** innerText（快速通读）。
        #   内容超过 {WEB_FETCH_MAX_CHARS} 字符时，完整文本写入
        #   ws:logs/browser_text/{{uuid}}.txt，返回 preview（前 {TOOL_RESULT_PREVIEW_CHARS} 字符）和 saved_to。
        #   style/script 等不可见元素按 textContent 返回（其内联内容可读）。
        #
        # ## detailed（可选，仅 children 模式生效）
        # true 时 self 与每个子节点附加：href/src（原始属性值，相对路径保留原样）、
        # style（内联样式）、content（textContent 完整，不截断不解析）。
        # 典型场景：read(selector="head", detailed=true) 枚举页面全部资源
        # （link/script/style 的 URL 与内联内容）；外部资源文件经 href/src
        # 获得 URL 后用 web_fetch 获取（相对路径需结合当前页面 URL 解析）。
        #
        # ## 返回
        # children 模式：
        # ```json
        # {"element": {"tag": "div", "id": "main", "class": "", "self_text": "...", "self_html": "<div id=\"main\">...</div>", "leaf": false},
        #  "children": [{"index": 0, "path": "0", "tag": "h1", "id": "", "class": "", "text": "摘要…", "child_count": 0, "leaf": true}],
        #  "total": 1}
        # ```
        # text 模式（未超限）：
        # ```json
        # {"mode": "text", "text": "...", "tab_title": "...", "tab_url": "..."}
        # ```
        # text 模式（超限）：
        # ```json
        # {"mode": "text", "preview": "...", "saved_to": "ws:logs/browser_text/abc123.txt", "total_chars": 60000, "tab_title": "...", "tab_url": "..."}
        # ```
        #
        # ## 何时使用
        # - **快速通读**：mode="text" 一次取区域全文（配合语义 selector 直达，
        #   如 selector="main" / selector="article"，避免从根逐层下钻）。
        # - **了解页面结构**：默认 children 模式，从根（不传 path）开始逐层下钻。
        # - **精确读取**：children 的 text 只是摘要，完整内容须对该子元素再发起 read。
        # - 深嵌套页面（如文档站）优先用 selector 直达正文容器，而非从 body 逐层走 path。
        #
        # ## 副作用/注意
        # - 只读查询，不修改浏览器状态；正常模式下无需审批。
        # - text 模式超限保存的文件为必定安全的网页文本，可用 Read 读取全文。
        "description": f"""Structured read of a page element; `mode` selects the return shape.

## Prerequisites
- browser_connect must have succeeded; the target tab exists; the target element is located (path from browser_query, or selector).

## mode
- "children" (default): returns the element's own form (excluding children) plus its next-level child list:
  1. `element` — the element's own form (**excluding children**): `self_text` (direct text nodes only, complete and untruncated), `self_html` (raw HTML form: clone with all child elements removed), `leaf` (has no child elements).
  2. `children` — next-level child elements, each with {{index, path, tag, id, class, text (subtree text summary, truncated), child_count, leaf}}.
  Filters (apply to children, combinable): filter_tag (exact tag match), filter_text (subtree visible text contains, descendants included, case-insensitive).
- "text": returns the **complete** innerText of the element's subtree (fast full read). Content exceeding {WEB_FETCH_MAX_CHARS} characters is saved to ws:logs/browser_text/{{uuid}}.txt and the result includes `preview` (first {TOOL_RESULT_PREVIEW_CHARS} characters) and `saved_to`. Invisible elements (style/script) are returned via textContent so their inline content is readable.

## detailed (optional, children mode only)
When true, `self` and every child additionally include: href/src (raw attribute values, relative paths kept as-is), style (inline styles), content (complete textContent, untruncated and unparsed). Typical use: read(selector="head", detailed=true) to enumerate all page resources (URLs and inline content of link/script/style); external resource files can then be fetched via web_fetch using the href/src URLs (resolve relative paths against the current page URL).

## Returns
children mode:
```json
{{"element": {{"tag": "div", "id": "main", "class": "", "self_text": "...", "self_html": "<div id=\"main\">...</div>", "leaf": false}},
 "children": [{{"index": 0, "path": "0", "tag": "h1", "id": "", "class": "", "text": "summary…", "child_count": 0, "leaf": true}}],
 "total": 1}}
```
text mode (normal):
```json
{{"mode": "text", "text": "...", "tab_title": "...", "tab_url": "..."}}
```
text mode (oversized):
```json
{{"mode": "text", "preview": "...", "saved_to": "ws:logs/browser_text/abc123.txt", "total_chars": 60000, "tab_title": "...", "tab_url": "..."}}
```

## When to Use
- **Fast full read**: mode="text" for the whole region at once (pair with semantic selectors like selector="main" / selector="article" instead of drilling from the root).
- **Understand structure**: default children mode, start from the root (omit path) and drill down layer by layer.
- **Precise read**: children text is only a summary — call browser_read on that child element again for the full content.
- On deeply nested pages (e.g. doc sites), prefer semantic selectors to jump straight to the content container instead of walking the path from body.

## Side Effects / Notes
- Read-only; does not modify browser state; no approval needed in normal mode.
- text-mode oversized saves are always-safe page text; use Read for the full content.""",
        "parameters": {
            "type": "object",
            "properties": {
                "tab": {
                    "type": "string",
                    # 目标标签页：browser_list_tabs 的 0 基 index（如 "0"），或 url/title 的子串。
                    "description": "Target tab: the 0-based index from browser_list_tabs (e.g. \"0\"), or a substring of its URL or title.",
                },
                "path": {
                    "type": "string",
                    # 元素索引路径（点分隔数字，如 "0.2.1"；空 = 页面根）。与 selector 二选一。
                    "description": "Element index path (dot-separated numbers like \"0.2.1\"; empty = page root). Mutually exclusive with selector.",
                    "default": "",
                },
                "selector": {
                    "type": "string",
                    # CSS 选择器或 XPath（以 / 开头自动识别），取首个匹配。与 path 二选一。
                    "description": "CSS selector or XPath (auto-detected when starting with '/'), first match is used. Mutually exclusive with path.",
                    "default": "",
                },
                "filter_tag": {
                    "type": "string",
                    # 只返回 tag 匹配的子元素（大小写不敏感）。
                    "description": "Keep only children whose tag matches exactly (case-insensitive).",
                    "default": "",
                },
                "filter_text": {
                    "type": "string",
                    # 只返回子树可见文本包含该文本的子元素（含后代，大小写不敏感）。
                    "description": "Keep only children whose subtree visible text contains this (descendants included, case-insensitive).",
                    "default": "",
                },
                "mode": {
                    "type": "string",
                    # 返回形态：children（默认，self + 一层子节点）/ text（子树完整 innerText）。
                    "description": "Return shape: 'children' (default, element + one layer of children) or 'text' (complete subtree innerText).",
                    "default": "children",
                },
                "detailed": {
                    "type": "boolean",
                    # 仅 children 模式生效：为 true 时 self 与每个子节点附加完整字段
                    # （href/src/style 原始属性值 + content 完整 textContent），
                    # 用于资源/内联内容查看（如 head 下的 link/script/style）。
                    # 注意：content 为 textContent 完整返回，不截断不解析，体积由调用方自负。
                    "description": "Children mode only: when true, self and each child include full fields (href/src/style raw attribute values + content complete textContent). Useful for inspecting resources and inline content (e.g. link/script/style under head). Note: content is returned in full, untruncated and unparsed — the caller owns the size.",
                    "default": False,
                },
            },
            "required": ["tab"],
        },
    },
    handler=_handle_browser_read,
    check_fn=_connection.playwright_available,
    is_async=True,
    emoji="📖",
    danger_level=ToolDangerLevel.readonly,
)