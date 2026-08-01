"""CDP 连接共享模块 — browser 工具组的连接单例与标签页定位。

模块级仅导入 stdlib；playwright 延迟到函数内导入。这是 check_fn
机制成立的前提：未安装 playwright 时本模块仍可被正常 import，
工具组仅对 LLM 隐藏而非导入失败。

连接为模块级单例，在 agent 主事件循环首次创建（工具经
``registry.async_dispatch`` 在主 loop 中 await）；每次调用前探活，
失效自动重建。
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import Browser, Page

logger = logging.getLogger(__name__)

CDP_ENDPOINT_DEFAULT: str = "http://localhost:9222"
CONNECT_TIMEOUT_MS: int = 5000
_CDP_VERSION_PATH: str = "/json/version"

# Windows 上 Edge 的常见安装路径（64 位系统默认装于 x86 目录）。
EDGE_CANDIDATE_PATHS: tuple[str, ...] = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)

# 面向终端用户的操作指引（agent 会转述），connect/launch 失败时共用。
# Chromium 136+ 起，默认用户数据目录下 --remote-debugging-port 被静默忽略，
# 必须配合非默认 --user-data-dir 使用。
EDGE_DEBUG_GUIDE: str = (
    "无法接管浏览器：CDP 端点不可达。优先请 agent 调用 browser_launch 自动启动调试 Edge；"
    "若需手动启动，请执行：\n"
    '   "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe" --remote-debugging-port=9222 --user-data-dir=C:\\edge-cdp-profile\n'
    "注意：Chromium 136+ 在默认用户数据目录下会静默忽略调试端口参数，必须指定非默认 --user-data-dir。"
)

_pw: Any = None        # playwright.async_api.Playwright
_browser: Any = None   # playwright.async_api.Browser
_endpoint: str = CDP_ENDPOINT_DEFAULT


def playwright_available() -> bool:
    """check_fn：playwright 可导入时 browser 工具组才对 LLM 可见。"""
    return importlib.util.find_spec("playwright") is not None


def edge_executable_path() -> str | None:
    """按顺序探测 Edge 可执行文件路径，均不存在时返回 None。"""
    for candidate in EDGE_CANDIDATE_PATHS:
        if Path(candidate).exists():
            return candidate
    return None


def probe_cdp_endpoint(endpoint: str = CDP_ENDPOINT_DEFAULT, timeout: float = 2.0) -> bool:
    """同步探测 CDP 端点是否可服务（GET /json/version 成功即视为就绪）。

    阻塞式网络调用，供 ``asyncio.to_thread`` 包装后使用，避免卡住事件循环。
    """
    try:
        with urllib.request.urlopen(f"{endpoint}{_CDP_VERSION_PATH}", timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


async def wait_for_endpoint(endpoint: str = CDP_ENDPOINT_DEFAULT, timeout_s: float = 20.0) -> bool:
    """轮询等待 CDP 端点就绪（0.5s 间隔），超时返回 False。"""
    deadline: float = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if await asyncio.to_thread(probe_cdp_endpoint, endpoint, 1.5):
            return True
        await asyncio.sleep(0.5)
    return False


def current_endpoint() -> str:
    """返回当前成功连接的 CDP 端点（未连接时为默认值）。"""
    return _endpoint


async def get_browser(endpoint: str = CDP_ENDPOINT_DEFAULT) -> "Browser":
    """返回存活的 Browser 连接；未连接或已断开则重建。

    连接失败时抛出异常，由调用方转换为引导错误。
    """
    global _pw, _browser, _endpoint
    if _browser is not None and _browser.is_connected():
        return _browser
    await teardown()
    from playwright.async_api import async_playwright
    _pw = await async_playwright().start()
    try:
        _browser = await _pw.chromium.connect_over_cdp(endpoint, timeout=CONNECT_TIMEOUT_MS)
    except Exception:
        await teardown()
        raise
    _endpoint = endpoint
    logger.info("browser CDP connected: %s", endpoint)
    return _browser


async def teardown() -> None:
    """断开 CDP 连接（不关闭用户浏览器）并释放 playwright。"""
    global _pw, _browser
    if _browser is not None:
        try:
            await _browser.close()
        except Exception:
            pass
        _browser = None
    if _pw is not None:
        try:
            await _pw.stop()
        except Exception:
            pass
        _pw = None


def all_pages(browser: "Browser") -> list["Page"]:
    """展平所有 browser contexts 的 pages。"""
    return [page for ctx in browser.contexts for page in ctx.pages]


async def find_page(browser: "Browser", tab: str) -> "Page | None":
    """按 *tab* 定位标签页。

    纯数字 → 按枚举顺序的 0 基 index；否则先 url 包含匹配、
    再 title 包含匹配（均大小写不敏感）。无匹配返回 None。
    """
    pages = all_pages(browser)
    tab = tab.strip()
    if tab.isdigit():
        idx = int(tab)
        return pages[idx] if 0 <= idx < len(pages) else None
    lowered = tab.lower()
    for page in pages:
        if lowered in (page.url or "").lower():
            return page
    for page in pages:
        try:
            title = await page.title()
        except Exception:
            continue  # 页面可能正在关闭，跳过
        if lowered in (title or "").lower():
            return page
    return None


# ---------------------------------------------------------------------------
# DOM 结构化查询（页面内 JS）
#
# 在页面上下文中通过 page.evaluate 执行，拿到的是浏览器渲染后的真实 DOM。
# 提供三种操作：
#   snapshot       — 目标元素（path 或 selector 定位）的自身形态 + 一层子节点
#   query_selector — CSS/XPath 定位，可选 text 过滤（交集）
#   query_text     — 全文查找子树文本包含指定文本的"最深匹配"元素
# 索引路径：点分隔数字（如 "0.2.1"），从 document.body 起算；空串 = 根。
# ---------------------------------------------------------------------------

DOM_TEXT_SUMMARY_CHARS: int = 80
QUERY_MAX_RESULTS: int = 50
QUERY_MAX_RESULTS_HARD: int = 200

_DOM_SCRIPT: str = r"""(args) => {
  const summaryChars = args.summary_chars || 80;
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const textOf = (el, chars) => { const t = norm(el.innerText); return t.length > chars ? t.slice(0, chars) + '…' : t; };
  const directText = (el) => {
    const parts = [];
    for (const node of el.childNodes) {
      if (node.nodeType === 3) { const t = norm(node.data); if (t) parts.push(t); }
    }
    return parts.join(' ');
  };
  const selfHtml = (el) => {
    const clone = el.cloneNode(true);
    while (clone.firstElementChild) clone.removeChild(clone.firstElementChild);
    return clone.outerHTML;
  };
  const clsOf = (el) => (typeof el.className === 'string' ? el.className.split(/\s+/).slice(0, 5).join(' ') : '');
  const pathOf = (el) => {
    const path = [];
    let cur = el;
    while (cur && cur !== document.body) {
      const parent = cur.parentElement;
      if (!parent) break;
      let idx = 0;
      for (let i = 0; i < parent.children.length; i++) { if (parent.children[i] === cur) { idx = i; break; } }
      path.unshift(idx);
      cur = parent;
    }
    return path;
  };
  const resolveByPath = (pathStr) => {
    if (!pathStr) return document.body;
    let el = document.body;
    for (const part of pathStr.split('.')) {
      const idx = Number(part);
      if (!Number.isInteger(idx) || idx < 0 || idx >= el.children.length) return null;
      el = el.children[idx];
    }
    return el;
  };
  const queryNodes = (selector) => {
    if (selector.startsWith('/')) {
      const res = document.evaluate(selector, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
      const nodes = [];
      for (let i = 0; i < res.snapshotLength; i++) nodes.push(res.snapshotItem(i));
      return nodes;
    }
    return Array.from(document.querySelectorAll(selector));
  };
  const childInfo = (el, basePath, idx) => ({
    index: idx,
    path: basePath ? basePath + '.' + idx : String(idx),
    tag: el.tagName.toLowerCase(),
    id: el.id || '',
    class: clsOf(el),
    text: textOf(el, summaryChars),
    child_count: el.children.length,
    leaf: el.children.length === 0,
    ...(args.detailed ? {
      href: el.getAttribute('href') || '',
      src: el.getAttribute('src') || '',
      style: el.getAttribute('style') || '',
      content: el.textContent || '',
    } : {}),
  });
  const elementInfo = (el) => ({
    tag: el.tagName.toLowerCase(),
    id: el.id || '',
    class: clsOf(el),
    self_text: directText(el),
    self_html: selfHtml(el),
    leaf: el.children.length === 0,
    ...(args.detailed ? {
      href: el.getAttribute('href') || '',
      src: el.getAttribute('src') || '',
      style: el.getAttribute('style') || '',
      content: el.textContent || '',
    } : {}),
  });

  if (args.op === 'snapshot') {
    let el = args.path ? resolveByPath(args.path) : null;
    if (!el && args.selector) {
      try { const nodes = queryNodes(args.selector); el = nodes.length ? nodes[0] : null; }
      catch (e) { return { error: 'invalid selector: ' + e.message }; }
    }
    if (!el) return { error: 'target not found' };
    const basePath = args.path || '';
    const children = [];
    for (let i = 0; i < el.children.length; i++) {
      const child = el.children[i];
      if (args.filter_tag && child.tagName.toLowerCase() !== args.filter_tag.toLowerCase()) continue;
      if (args.filter_text && (child.innerText || '').toLowerCase().indexOf(String(args.filter_text).toLowerCase()) === -1) continue;
      children.push(childInfo(child, basePath, i));
    }
    return { element: elementInfo(el), children, total: children.length };
  }

  if (args.op === 'query_selector') {
    let nodes;
    try { nodes = queryNodes(args.selector); }
    catch (e) { return { error: 'invalid selector: ' + e.message }; }
    const needle = args.filter_text ? String(args.filter_text).toLowerCase() : null;
    const matches = [];
    for (let i = 0; i < nodes.length; i++) {
      const el = nodes[i];
      if (el.nodeType !== 1) continue;
      if (needle !== null && (el.innerText || '').toLowerCase().indexOf(needle) === -1) continue;
      const p = pathOf(el);
      matches.push({
        path: p.join('.'),
        tag: el.tagName.toLowerCase(),
        id: el.id || '',
        class: clsOf(el),
        text: textOf(el, summaryChars),
        child_count: el.children.length,
        leaf: el.children.length === 0,
      });
    }
    const total = matches.length;
    const truncated = total > args.max_results;
    return { matches: matches.slice(0, args.max_results), total, truncated };
  }

  if (args.op === 'query_text') {
    const needle = String(args.text).toLowerCase();
    const matches = [];
    const walk = (el) => {
      let childMatched = false;
      for (let i = 0; i < el.children.length; i++) {
        if (walk(el.children[i])) childMatched = true;
      }
      if (childMatched) return false;
      if ((el.innerText || '').toLowerCase().indexOf(needle) === -1) return false;
      const p = pathOf(el);
      matches.push({
        path: p.join('.'),
        tag: el.tagName.toLowerCase(),
        id: el.id || '',
        class: clsOf(el),
        text: textOf(el, summaryChars),
        child_count: el.children.length,
        leaf: el.children.length === 0,
      });
      return true;
    };
    walk(document.body);
    const total = matches.length;
    const truncated = total > args.max_results;
    return { matches: matches.slice(0, args.max_results), total, truncated };
  }

  if (args.op === 'text') {
    let el = args.path ? resolveByPath(args.path) : null;
    if (!el && args.selector) {
      try { const nodes = queryNodes(args.selector); el = nodes.length ? nodes[0] : null; }
      catch (e) { return { error: 'invalid selector: ' + e.message }; }
    }
    if (!el) return { error: 'target not found' };
    // style/script/template/noscript 等不可见元素 innerText 恒为空，须用 textContent 才能读到内容。
    const tag = el.tagName;
    const text = (tag === 'STYLE' || tag === 'SCRIPT' || tag === 'TEMPLATE' || tag === 'NOSCRIPT')
      ? (el.textContent || '')
      : (el.innerText || '');
    return { text };
  }

  return { error: 'unknown op: ' + args.op };
}"""


async def _eval_dom(page: "Page", op: str, **params: Any) -> dict:
    """在页面上下文中执行 DOM 查询脚本并校验返回形态。"""
    result = await page.evaluate(_DOM_SCRIPT, {"op": op, **params})
    if not isinstance(result, dict):
        return {"error": f"unexpected DOM result: {type(result).__name__}"}
    return result


async def dom_snapshot(
    page: "Page",
    path: str = "",
    selector: str = "",
    filter_tag: str = "",
    filter_text: str = "",
    detailed: bool = False,
) -> dict:
    """返回目标元素的自身形态（self_text/self_html，不含子元素）+ 一层子节点快照。

    *detailed* 为 True 时，self 与每个子节点附加完整字段
    （href/src/style 原始属性值 + content 完整 textContent）。
    """
    return await _eval_dom(
        page, "snapshot",
        path=path, selector=selector,
        filter_tag=filter_tag, filter_text=filter_text,
        detailed=detailed,
        summary_chars=DOM_TEXT_SUMMARY_CHARS,
    )


async def dom_query_selector(page: "Page", selector: str, max_results: int, filter_text: str = "") -> dict:
    """CSS/XPath 定位元素引用列表，可选 text 过滤（交集）。"""
    return await _eval_dom(
        page, "query_selector",
        selector=selector, max_results=max_results,
        filter_text=filter_text, summary_chars=DOM_TEXT_SUMMARY_CHARS,
    )


async def dom_query_text(page: "Page", text: str, max_results: int) -> dict:
    """全文查找子树文本包含 *text* 的最深匹配元素引用列表。"""
    return await _eval_dom(
        page, "query_text",
        text=text, max_results=max_results,
        summary_chars=DOM_TEXT_SUMMARY_CHARS,
    )


async def dom_text(page: "Page", path: str = "", selector: str = "") -> dict:
    """返回指定元素的子树完整 innerText（快速通读，超限由调用方处理）。"""
    return await _eval_dom(page, "text", path=path, selector=selector)


# ---------------------------------------------------------------------------
# 操作定位：path/selector → playwright Locator
# ---------------------------------------------------------------------------

def path_to_xpath(path: str) -> str:
    """索引路径 → XPath locator 字符串。

    0 基 index 转 XPath 1 基（`*[n+1]`），与 children 的 index 语义一致。
    非数字部分视为非法路径并抛出 ValueError，避免静默回退到根元素。
    """
    path = path.strip()
    if not path:
        return "//body"
    indices: list[str] = []
    for part in path.split("."):
        part = part.strip()
        if not part.isdigit():
            raise ValueError(f"invalid path segment: {part!r} (path must be dot-separated numbers)")
        indices.append(f"*[{int(part) + 1}]")
    return "//body/" + "/".join(indices)


def resolve_locator(page: "Page", path: str = "", selector: str = "") -> Any:
    """按 *path*（XPath）或 *selector*（CSS）解析 playwright Locator。

    调用方以 ``locator.count() == 0`` 判断目标元素不存在；
    *path* 非法时抛出 ValueError。
    """
    if path:
        return page.locator(f"xpath={path_to_xpath(path)}")
    return page.locator(selector)