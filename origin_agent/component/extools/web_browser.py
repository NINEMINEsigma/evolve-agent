"""Browser automation tools wrapping agent-browser CLI.

Each tool invokes agent-browser via subprocess with ``--session evolve``
to maintain a persistent browser session across tool calls.
``browser_close`` terminates the session.

Module-import-time registration via ``registry.register()``.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from abstract.tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)

_SESSION_NAME: str = "evolve"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# agent-browser binary resolution
# ---------------------------------------------------------------------------

_AB_CMD: str | None = None


def _resolve_ab_cmd() -> str | None:
    """Find the full path to agent-browser.

    Tries in order:
      1. ``shutil.which("agent-browser")`` — Python's native PATH lookup
      2. ``pnpm bin -g`` — pnpm's global bin directory (user confirmed pnpm works)
      3. ``npx --no-install agent-browser --version`` — Node.js global resolver
      4. Hardcoded common install directories
    Returns the full path string, or None if not found.
    """
    global _AB_CMD
    if _AB_CMD is not None:
        return _AB_CMD

    import os
    import shutil

    binary_names = ["agent-browser.cmd", "agent-browser.exe", "agent-browser"]

    # ------------------------------------------------------------------
    # 1. Python shutil.which() — uses os.environ["PATH"]
    # ------------------------------------------------------------------
    for name in binary_names:
        try:
            p = shutil.which(name)
            if p:
                _AB_CMD = p
                return _AB_CMD
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 2. pnpm bin -g — get the global bin directory from pnpm directly.
    #    The user confirmed pnpm works inside the agent.
    # ------------------------------------------------------------------
    try:
        proc = subprocess.run(
            ["pnpm", "bin", "-g"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0:
            bin_dir = proc.stdout.strip()
            if bin_dir:
                for name in binary_names:
                    p = os.path.join(bin_dir, name)
                    if os.path.isfile(p):
                        _AB_CMD = p
                        logger.info("Found agent-browser via pnpm bin: %s", p)
                        return _AB_CMD
    except Exception as exc:
        logger.debug("pnpm bin -g failed: %s", exc)

    # ------------------------------------------------------------------
    # 3. npx --no-install — Node.js global package resolver
    # ------------------------------------------------------------------
    try:
        proc = subprocess.run(
            ["npx", "--no-install", "agent-browser", "--version"],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode == 0:
            # npx found it — subsequent calls will use npx too
            global _AB_USE_NPX
            _AB_USE_NPX = True
            _AB_CMD = "npx"
            logger.info("agent-browser resolved via npx --no-install")
            return _AB_CMD
    except Exception as exc:
        logger.debug("npx --no-install failed: %s", exc)

    # ------------------------------------------------------------------
    # 4. Hardcoded common global install directories
    # ------------------------------------------------------------------
    home = os.path.expanduser("~")
    candidates = [
        os.environ.get("APPDATA", "") + "\\npm\\agent-browser.cmd",
        os.environ.get("LOCALAPPDATA", "") + "\\pnpm\\agent-browser.cmd",
        home + "\\AppData\\Roaming\\npm\\agent-browser.cmd",
        home + "\\AppData\\Local\\pnpm\\agent-browser.cmd",
        home + "\\pnpm\\bin\\agent-browser.cmd",
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            _AB_CMD = candidate
            logger.info("Found agent-browser at hardcoded path: %s", candidate)
            return _AB_CMD

    # Log PATH for debugging
    logger.warning(
        "agent-browser not found. PATH=%s",
        os.environ.get("PATH", "").replace(os.pathsep, "\n  "),
    )
    return None


_AB_USE_NPX: bool = False


def _check_binary() -> str | None:
    """Return None if agent-browser CLI is available, or an error message."""
    cmd = _resolve_ab_cmd()
    if cmd is None:
        return (
            "需要安装 agent-browser:\n"
            "  pnpm i -g agent-browser && agent-browser install\n"
            "安装后重启 agent 即可使用浏览器工具。\n"
            "如果已安装但仍找不到，请尝试在 terminal 中运行:\n"
            "  where agent-browser\n"
            "  pnpm bin -g"
        )
    try:
        if _AB_USE_NPX:
            check_cmd = ["npx", "--no-install", "agent-browser", "--version"]
        else:
            check_cmd = [cmd, "--version"]
        proc = subprocess.run(check_cmd, capture_output=True, text=True, timeout=10)
        if proc.returncode == 0:
            return None
        # npx exit code != 0 means the package isn't found globally
        return f"agent-browser 检查失败 (exit={proc.returncode}): {proc.stderr or proc.stdout or ''}"
    except subprocess.TimeoutExpired:
        return "agent-browser 检查超时，请确认安装是否正确。"


def _build_ab_cmd(*args: str) -> list[str]:
    """Build the agent-browser command list based on resolution method."""
    cmd = _resolve_ab_cmd()
    if cmd is None:
        raise RuntimeError(
            "agent-browser 未安装，请运行: pnpm i -g agent-browser && agent-browser install"
        )
    if _AB_USE_NPX:
        return ["npx", "--no-install", "agent-browser", "--session", _SESSION_NAME, *args]
    return [cmd, "--session", _SESSION_NAME, *args]


def _run_ab(*args: str, timeout: int = 60) -> str:
    """Run agent-browser with the given arguments and return stdout.

    Raises RuntimeError on non-zero exit.
    """
    try:
        full_cmd = _build_ab_cmd(*args)
    except RuntimeError as exc:
        raise exc

    try:
        proc = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        # Clear cached path — it may have been deleted
        global _AB_CMD
        _AB_CMD = None
        raise RuntimeError(
            "agent-browser 未安装，请运行: pnpm i -g agent-browser && agent-browser install"
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"命令超时 ({timeout}s): {' '.join(full_cmd)}")

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        hint = ""
        if "not found" in stderr.lower() or "unknown command" in stderr.lower():
            hint = "\n可能是 agent-browser 版本过旧，请运行: pnpm i -g agent-browser@latest"
        raise RuntimeError(f"agent-browser 返回错误 ({proc.returncode}): {stderr}{hint}")

    return proc.stdout


# Lazy import of Sandbox (set at runtime by main.py)
_fs_sandbox: Any | None = None


def _get_sandbox():
    global _fs_sandbox
    if _fs_sandbox is None:
        from component.tools.filesystem import _sandbox
        _fs_sandbox = _sandbox
    return _fs_sandbox


def _ws_path(*parts: str) -> tuple[Path, str]:
    """Build a path under ws: for file output.

    Returns (real_fs_path, http_rel like "browser/xxx.png").
    Uses the Sandbox to resolve ws: to the agentspace directory so
    the /uploads/ route can serve the file.
    """
    rel = str(Path("browser") / Path(*parts)).replace("\\", "/")
    sb = _get_sandbox()
    if sb is not None:
        try:
            agentspace = sb._ctx.agentspace
            fs_path = (agentspace / rel.replace("/", "\\")).resolve()
            fs_path.parent.mkdir(parents=True, exist_ok=True)
            return fs_path, rel
        except Exception:
            pass
    fs_path = (Path.cwd() / rel.replace("/", "\\")).resolve()
    fs_path.parent.mkdir(parents=True, exist_ok=True)
    return fs_path, rel


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def _handle_browser_navigate(args: Dict[str, Any]) -> str:
    """Open a URL and return the page snapshot."""
    err = _check_binary()
    if err:
        return tool_error(err)

    url: str = (args.get("url") or "").strip()
    if not url:
        return tool_error("url is required")

    try:
        _run_ab("open", url)
        snapshot = _run_ab("snapshot", "-i", "-c")
        return tool_result(
            url=url,
            snapshot=snapshot,
            instruction=(
                "页面已加载。使用 browser_snapshot 获取最新状态，"
                "使用 @eN ref 与元素交互。"
            ),
        )
    except RuntimeError as exc:
        return tool_error(str(exc))


def _handle_browser_snapshot(args: Dict[str, Any]) -> str:
    """Return the current page's interactive element tree."""
    err = _check_binary()
    if err:
        return tool_error(err)

    deep: bool = args.get("full", False)
    try:
        flags = ["-i"]
        if not deep:
            flags.extend(["-d", "4"])
        snapshot = _run_ab("snapshot", *flags)
        return tool_result(
            snapshot=snapshot,
            instruction=(
                "使用 @eN ref 与元素交互（如 browser_click @e3）。"
                "页面变化后需重新 snapshot。"
            ),
        )
    except RuntimeError as exc:
        return tool_error(str(exc))


def _handle_browser_click(args: Dict[str, Any]) -> str:
    """Click an element by @eN ref or CSS selector."""
    err = _check_binary()
    if err:
        return tool_error(err)

    ref: str = (args.get("ref") or "").strip()
    selector: str = (args.get("selector") or "").strip()
    if not ref and not selector:
        return tool_error("ref (如 @e3) 或 CSS selector 至少需要一个")

    target = ref if ref else selector
    try:
        _run_ab("click", target)
        # Auto-snapshot after click
        snapshot = _run_ab("snapshot", "-i", "-c", "-d", "4")
        return tool_result(
            clicked=target,
            snapshot=snapshot,
            instruction="元素已点击，当前页面状态如 snapshot 所示。",
        )
    except RuntimeError as exc:
        return tool_error(str(exc))


def _handle_browser_fill(args: Dict[str, Any]) -> str:
    """Fill an input element with text (clear + type)."""
    err = _check_binary()
    if err:
        return tool_error(err)

    ref: str = (args.get("ref") or "").strip()
    text: str = str(args.get("text") or "")
    if not ref:
        return tool_error("ref (如 @e3) 是必填的")
    if not text:
        return tool_error("text 是必填的")

    try:
        _run_ab("fill", ref, text)
        return tool_result(
            filled=ref,
            value=text,
            message="输入框已填充。",
        )
    except RuntimeError as exc:
        return tool_error(str(exc))


def _handle_browser_type(args: Dict[str, Any]) -> str:
    """Type text without clearing (append to existing content)."""
    err = _check_binary()
    if err:
        return tool_error(err)

    ref: str = (args.get("ref") or "").strip()
    text: str = str(args.get("text") or "")
    if not ref:
        return tool_error("ref (如 @e3) 是必填的")

    try:
        if text:
            _run_ab("type", ref, text)
        else:
            # No text means just focus the element
            _run_ab("focus", ref)
        return tool_result(
            typed=ref,
            value=text or "(focused)",
            message="输入完成。" if text else "元素已聚焦。",
        )
    except RuntimeError as exc:
        return tool_error(str(exc))


def _handle_browser_press_key(args: Dict[str, Any]) -> str:
    """Press a keyboard key (Enter, Tab, Escape, etc.)."""
    err = _check_binary()
    if err:
        return tool_error(err)

    key: str = (args.get("key") or "Enter").strip()
    try:
        _run_ab("press", key)
        snapshot = _run_ab("snapshot", "-i", "-c", "-d", "4")
        return tool_result(
            key=key,
            snapshot=snapshot,
            instruction=f"按键 {key} 已发送。",
        )
    except RuntimeError as exc:
        return tool_error(str(exc))


def _handle_browser_screenshot(args: Dict[str, Any]) -> str:
    """Take a screenshot and save to ws:, return markdown image URL."""
    err = _check_binary()
    if err:
        return tool_error(err)

    name: str = (args.get("name") or "screenshot.png").strip()
    full_page: bool = args.get("full_page", False)

    try:
        # _ws_path now returns (real_fs_path, http_rel)
        fs_path, rel_path = _ws_path(name)

        cmd_parts = ["screenshot", str(fs_path)]
        if full_page:
            cmd_parts.append("--full")
        _run_ab(*cmd_parts)

        md_link = f"![screenshot](/uploads/{rel_path})"
        return tool_result(
            path=f"ws:{rel_path}",
            markdown=md_link,
            message=f"截图已保存: ws:{rel_path}",
        )
    except RuntimeError as exc:
        return tool_error(str(exc))


def _handle_browser_get_text(args: Dict[str, Any]) -> str:
    """Extract visible text from an element."""
    err = _check_binary()
    if err:
        return tool_error(err)

    ref: str = (args.get("ref") or "").strip()
    if not ref:
        return tool_error("ref (如 @e3) 是必填的")

    try:
        text = _run_ab("get", "text", ref)
        return tool_result(text=text.strip() if text else "")
    except RuntimeError as exc:
        return tool_error(str(exc))


def _handle_browser_eval(args: Dict[str, Any]) -> str:
    """Execute JavaScript in the page context."""
    err = _check_binary()
    if err:
        return tool_error(err)

    code: str = str(args.get("code") or "")
    if not code:
        return tool_error("code 是必填的")

    try:
        result = _run_ab("eval", code)
        return tool_result(result=result.strip() if result else "")
    except RuntimeError as exc:
        return tool_error(str(exc))


def _handle_browser_wait(args: Dict[str, Any]) -> str:
    """Wait for a page condition."""
    err = _check_binary()
    if err:
        return tool_error(err)

    condition: str = (args.get("condition") or "networkidle").strip()
    value: str = (args.get("value") or "").strip()
    timeout_s: int = int(args.get("timeout", 25))

    try:
        if condition == "networkidle":
            _run_ab("wait", "--load", "networkidle", timeout=timeout_s)
        elif condition == "text" and value:
            _run_ab("wait", "--text", value)
        elif condition == "url" and value:
            _run_ab("wait", "--url", value)
        elif condition == "element" and value:
            _run_ab("wait", value, timeout=timeout_s)
        else:
            _run_ab("wait", str(max(1, timeout_s * 1000)))  # ms

        snapshot = _run_ab("snapshot", "-i", "-c", "-d", "4")
        return tool_result(
            snapshot=snapshot,
            message="等待完成，页面已就绪。",
        )
    except RuntimeError as exc:
        return tool_error(str(exc))


def _handle_browser_close(args: Dict[str, Any]) -> str:
    """Close the browser session."""
    err = _check_binary()
    if err:
        return tool_error(err)

    try:
        _run_ab("close")
        return tool_result(message="浏览器会话已关闭。")
    except RuntimeError as exc:
        return tool_error(str(exc))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_INSTALL_HINT = (
    "需要 agent-browser CLI:\n  pnpm i -g agent-browser && agent-browser install\n"
)

registry.register(
    name="browser_navigate",
    toolset="browser",
    schema={
        "description": "在浏览器中打开 URL 并返回页面可交互元素的 snapshot。需要 agent-browser 已安装。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要打开的完整 URL（含 https://）。",
                },
            },
            "required": ["url"],
        },
    },
    handler=_handle_browser_navigate,
    emoji="🌐",
)

registry.register(
    name="browser_snapshot",
    toolset="browser",
    schema={
        "description": "获取当前浏览页面的可交互元素树（@eN ref），用于了解页面状态。",
        "parameters": {
            "type": "object",
            "properties": {
                "full": {
                    "type": "boolean",
                    "description": "设为 true 获取完整深度（默认限制 4 层）。",
                },
            },
        },
    },
    handler=_handle_browser_snapshot,
    emoji="📋",
)

registry.register(
    name="browser_click",
    toolset="browser",
    schema={
        "description": "通过 @eN ref 或 CSS 选择器点击页面元素。点击后自动 snapshot 返回最新状态。",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    "description": "元素的 @eN ref（如 @e3），来自 browser_navigate 或 browser_snapshot。",
                },
                "selector": {
                    "type": "string",
                    "description": "CSS 选择器（当 ref 不可用时使用）。",
                },
            },
        },
    },
    handler=_handle_browser_click,
    emoji="🖱️",
)

registry.register(
    name="browser_fill",
    toolset="browser",
    schema={
        "description": "清空输入框并填入指定文本。",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    "description": "输入框的 @eN ref。",
                },
                "text": {
                    "type": "string",
                    "description": "要填入的文本。",
                },
            },
            "required": ["ref", "text"],
        },
    },
    handler=_handle_browser_fill,
    emoji="✏️",
)

registry.register(
    name="browser_type",
    toolset="browser",
    schema={
        "description": "在输入框中逐字输入文本（不清空已有内容）。不带 text 时仅聚焦元素。",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    "description": "输入框的 @eN ref。",
                },
                "text": {
                    "type": "string",
                    "description": "要追加的文本（可选，留空则聚焦）。",
                },
            },
            "required": ["ref"],
        },
    },
    handler=_handle_browser_type,
    emoji="⌨️",
)

registry.register(
    name="browser_press_key",
    toolset="browser",
    schema={
        "description": "发送键盘按键（Enter, Tab, Escape, ArrowDown 等）。通常用于提交表单或导航。",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "按键名，如 Enter, Tab, Escape, ArrowDown 等。",
                },
            },
        },
    },
    handler=_handle_browser_press_key,
    emoji="🔑",
)

registry.register(
    name="browser_screenshot",
    toolset="browser",
    schema={
        "description": "对当前页面截图并保存到 workspace。返回 Markdown 图片链接，前端可直接显示。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "截图文件名（如 screenshot.png）。",
                },
                "full_page": {
                    "type": "boolean",
                    "description": "是否截取整页（包括滚动区域）。",
                },
            },
        },
    },
    handler=_handle_browser_screenshot,
    emoji="📸",
)

registry.register(
    name="browser_get_text",
    toolset="browser",
    schema={
        "description": "提取指定元素的可见文本内容。",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    "description": "元素的 @eN ref。",
                },
            },
            "required": ["ref"],
        },
    },
    handler=_handle_browser_get_text,
    emoji="📄",
)

registry.register(
    name="browser_eval",
    toolset="browser",
    schema={
        "description": "在浏览器页面上下文中执行 JavaScript 代码并返回结果。",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "要执行的 JavaScript 代码。支持多行。",
                },
            },
            "required": ["code"],
        },
    },
    handler=_handle_browser_eval,
    emoji="⚡",
)

registry.register(
    name="browser_wait",
    toolset="browser",
    schema={
        "description": "等待页面条件就绪（网络空闲、特定文本/元素出现、URL 变化等）。",
        "parameters": {
            "type": "object",
            "properties": {
                "condition": {
                    "type": "string",
                    "enum": ["networkidle", "text", "url", "element"],
                    "description": "等待条件: networkidle(默认), text(文本出现), url(URL 匹配), element(元素出现)。",
                },
                "value": {
                    "type": "string",
                    "description": "条件值（text/url/element 时必填）。",
                },
                "timeout": {
                    "type": "integer",
                    "description": "超时秒数（默认 25）。",
                },
            },
        },
    },
    handler=_handle_browser_wait,
    emoji="⏳",
)

registry.register(
    name="browser_close",
    toolset="browser",
    schema={
        "description": "关闭当前浏览器会话，释放资源。",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    handler=_handle_browser_close,
    emoji="🚪",
)