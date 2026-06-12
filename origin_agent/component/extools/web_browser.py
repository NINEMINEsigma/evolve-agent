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
      0. ``pnpm exec agent-browser --version`` — pnpm's own package resolution (most reliable for pnpm users)
      1. ``shutil.which("agent-browser")`` — Python's native PATH lookup
      2. ``pnpm bin -g`` — pnpm's global bin directory
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
    # 0. pnpm exec — pnpm's own package resolution.
    #    Most reliable for users who installed agent-browser via pnpm,
    #    because pnpm knows exactly where its global packages live,
    #    regardless of PATH configuration.
    # ------------------------------------------------------------------
    try:
        proc = subprocess.run(
            ["pnpm", "exec", "agent-browser", "--version"],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode == 0:
            global _AB_USE_PNPM_EXEC
            _AB_USE_PNPM_EXEC = True
            _AB_CMD = "pnpm"
            logger.info("agent-browser resolved via pnpm exec")
            return _AB_CMD
    except Exception as exc:
        logger.debug("pnpm exec failed: %s", exc)

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
_AB_USE_PNPM_EXEC: bool = False
_HEADED: bool = True  # 设为 True 显示浏览器窗口，False 则无头运行


def _check_binary() -> str | None:
    """Return None if agent-browser CLI is available, or an error message."""
    cmd = _resolve_ab_cmd()
    if cmd is None:
        return (
            "agent-browser needs to be installed:\n"
            "  pnpm i -g agent-browser && agent-browser install\n"
            "Restart the agent after installation to use browser tools.\n"
            "If still not found, try running in terminal:\n"
            "  where agent-browser\n"
            "  pnpm bin -g"
        )
    try:
        if _AB_USE_PNPM_EXEC:
            check_cmd = ["pnpm", "exec", "agent-browser", "--version"]
        elif _AB_USE_NPX:
            check_cmd = ["npx", "--no-install", "agent-browser", "--version"]
        else:
            check_cmd = [cmd, "--version"]
        proc = subprocess.run(check_cmd, capture_output=True, text=True, timeout=10)
        if proc.returncode == 0:
            return None
        return f"agent-browser check failed (exit={proc.returncode}): {proc.stderr or proc.stdout or ''}"
    except FileNotFoundError:
        return "agent-browser command not found. Please ensure pnpm or agent-browser is in your PATH."
    except subprocess.TimeoutExpired:
        return "agent-browser check timed out. Please verify the installation is correct."


def _build_ab_cmd(*args: str) -> list[str]:
    """Build the agent-browser command list based on resolution method."""
    cmd = _resolve_ab_cmd()
    if cmd is None:
        raise RuntimeError(
            "agent-browser is not installed. Run: pnpm i -g agent-browser && agent-browser install"
        )
    headed_flags: list[str] = ["--headed"] if _HEADED else []
    if _AB_USE_PNPM_EXEC:
        return ["pnpm", "exec", "agent-browser", "--session", _SESSION_NAME, *headed_flags, *args]
    if _AB_USE_NPX:
        return ["npx", "--no-install", "agent-browser", "--session", _SESSION_NAME, *headed_flags, *args]
    return [cmd, "--session", _SESSION_NAME, *headed_flags, *args]


def _run_ab(*args: str, timeout: int = 60) -> str:
    """Run agent-browser with the given arguments and return stdout.

    Raises RuntimeError on non-zero exit.
    """
    try:
        full_cmd = _build_ab_cmd(*args)
    except RuntimeError as exc:
        raise exc

    # On Windows, pnpm exec / npx are .cmd scripts that re-shell args
    # through cmd.exe, interpreting & | > < as command separators.
    # Use shell=True with double-quoted special-chars args to avoid this.
    shell_mode: bool = False
    if sys.platform == "win32" and (_AB_USE_PNPM_EXEC or _AB_USE_NPX):
        shell_mode = True
        escaped: list[str] = [
            f'"{a}"' if any(c in a for c in "&|><^%") else a
            for a in full_cmd
        ]
        full_cmd = " ".join(escaped)

    try:
        proc = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=shell_mode,
        )
    except FileNotFoundError:
        # Clear cached path — it may have been deleted
        global _AB_CMD
        _AB_CMD = None
        raise RuntimeError(
            "agent-browser is not installed. Run: pnpm i -g agent-browser && agent-browser install"
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"命令超时 ({timeout}s): {' '.join(full_cmd)}")

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        hint = ""
        if "not found" in stderr.lower() or "unknown command" in stderr.lower():
            hint = "\nPossibly agent-browser version is outdated, run: pnpm i -g agent-browser@latest"
        raise RuntimeError(f"agent-browser returned error ({proc.returncode}): {stderr}{hint}")

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


def _handle_browser_navigate(args: Dict[str, Any]) -> dict:
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
                "Page loaded. Use browser_snapshot for latest state, "
                "use @eN ref to interact with elements."
            ),
        )
    except RuntimeError as exc:
        return tool_error(str(exc))


def _handle_browser_snapshot(args: Dict[str, Any]) -> dict:
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
                "Use @eN ref to interact with elements (e.g. browser_click @e3). "
                "Re-snapshot after page changes."
            ),
        )
    except RuntimeError as exc:
        return tool_error(str(exc))


def _handle_browser_click(args: Dict[str, Any]) -> dict:
    """Click an element by @eN ref or CSS selector."""
    err = _check_binary()
    if err:
        return tool_error(err)

    ref: str = (args.get("ref") or "").strip()
    selector: str = (args.get("selector") or "").strip()
    if not ref and not selector:
        return tool_error("ref (e.g. @e3) or CSS selector is required")

    target = ref if ref else selector
    try:
        _run_ab("click", target)
        # Auto-snapshot after click
        snapshot = _run_ab("snapshot", "-i", "-c", "-d", "4")
        return tool_result(
            clicked=target,
            snapshot=snapshot,
            instruction="Element clicked, current page state shown in snapshot.",
        )
    except RuntimeError as exc:
        return tool_error(str(exc))


def _handle_browser_fill(args: Dict[str, Any]) -> dict:
    """Fill an input element with text (clear + type)."""
    err = _check_binary()
    if err:
        return tool_error(err)

    ref: str = (args.get("ref") or "").strip()
    text: str = str(args.get("text") or "")
    if not ref:
        return tool_error("ref (e.g. @e3) is required")
    if not text:
        return tool_error("text is required")

    try:
        _run_ab("fill", ref, text)
        return tool_result(
            filled=ref,
            value=text,
            message="Input field filled.",
        )
    except RuntimeError as exc:
        return tool_error(str(exc))


def _handle_browser_type(args: Dict[str, Any]) -> dict:
    """Type text without clearing (append to existing content)."""
    err = _check_binary()
    if err:
        return tool_error(err)

    ref: str = (args.get("ref") or "").strip()
    text: str = str(args.get("text") or "")
    if not ref:
        return tool_error("ref (e.g. @e3) is required")

    try:
        if text:
            _run_ab("type", ref, text)
        else:
            # No text means just focus the element
            _run_ab("focus", ref)
        return tool_result(
            typed=ref,
            value=text or "(focused)",
            message="Input complete." if text else "Element focused.",
        )
    except RuntimeError as exc:
        return tool_error(str(exc))


def _handle_browser_press_key(args: Dict[str, Any]) -> dict:
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
            instruction=f"Key {key} sent.",
        )
    except RuntimeError as exc:
        return tool_error(str(exc))


def _handle_browser_screenshot(args: Dict[str, Any]) -> dict:
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
            message=f"Screenshot saved: ws:{rel_path}",
        )
    except RuntimeError as exc:
        return tool_error(str(exc))


def _handle_browser_get_text(args: Dict[str, Any]) -> dict:
    """Extract visible text from an element."""
    err = _check_binary()
    if err:
        return tool_error(err)

    ref: str = (args.get("ref") or "").strip()
    if not ref:
        return tool_error("ref (e.g. @e3) is required")

    try:
        text = _run_ab("get", "text", ref)
        return tool_result(text=text.strip() if text else "")
    except RuntimeError as exc:
        return tool_error(str(exc))


def _handle_browser_eval(args: Dict[str, Any]) -> dict:
    """Execute JavaScript in the page context."""
    err = _check_binary()
    if err:
        return tool_error(err)

    code: str = str(args.get("code") or "")
    if not code:
        return tool_error("code is required")

    try:
        result = _run_ab("eval", code)
        return tool_result(result=result.strip() if result else "")
    except RuntimeError as exc:
        return tool_error(str(exc))


def _handle_browser_wait(args: Dict[str, Any]) -> dict:
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
            message="Wait complete, page ready.",
        )
    except RuntimeError as exc:
        return tool_error(str(exc))


def _handle_browser_close(args: Dict[str, Any]) -> dict:
    """Close the browser session."""
    err = _check_binary()
    if err:
        return tool_error(err)

    try:
        _run_ab("close")
        return tool_result(message="Browser session closed.")
    except RuntimeError as exc:
        return tool_error(str(exc))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_INSTALL_HINT = (
    "agent-browser CLI is required:\n  pnpm i -g agent-browser && agent-browser install\n"
)

registry.register(
    name="browser_navigate",
    toolset="browser",
    schema={
        # 在浏览器中打开 URL 并返回页面可交互元素的 snapshot。需要 agent-browser 已安装。
        "description": "Open a URL in the browser and return a snapshot of interactive elements. Requires agent-browser to be installed.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    # 要打开的完整 URL（含 https://）。
                    "description": "Full URL to open (including https://).",
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
        # 获取当前浏览页面的可交互元素树（@eN ref），用于了解页面状态。
        "description": "Get the interactive element tree (@eN ref) of the current page to understand page state.",
        "parameters": {
            "type": "object",
            "properties": {
                "full": {
                    "type": "boolean",
                    # 设为 true 获取完整深度（默认限制 4 层）。
                    "description": "Set to true for full depth (default limited to 4 levels).",
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
        # 通过 @eN ref 或 CSS 选择器点击页面元素。点击后自动 snapshot 返回最新状态。
        "description": "Click a page element via @eN ref or CSS selector. Auto-snapshots after click returning latest state.",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    # 元素的 @eN ref（如 @e3），来自 browser_navigate 或 browser_snapshot。
                    "description": "@eN ref of the element (e.g. @e3), from browser_navigate or browser_snapshot.",
                },
                "selector": {
                    "type": "string",
                    # CSS 选择器（当 ref 不可用时使用）。
                    "description": "CSS selector (used when ref is not available).",
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
        # 清空输入框并填入指定文本。
        "description": "Clear the input field and fill with specified text.",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    # 输入框的 @eN ref。
                    "description": "@eN ref of the input field.",
                },
                "text": {
                    "type": "string",
                    # 要填入的文本。
                    "description": "Text to fill in.",
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
        # 在输入框中逐字输入文本（不清空已有内容）。不带 text 时仅聚焦元素。
        "description": "Type text character by character into an input field (does not clear existing content). Without text, just focuses the element.",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    # 输入框的 @eN ref。
                    "description": "@eN ref of the input field.",
                },
                "text": {
                    "type": "string",
                    # 要追加的文本（可选，留空则聚焦）。
                    "description": "Text to type (optional, leave empty to focus).",
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
        # 发送键盘按键（Enter, Tab, Escape, ArrowDown 等）。通常用于提交表单或导航。
        "description": "Send keyboard keys (Enter, Tab, Escape, ArrowDown, etc.). Typically used for form submission or navigation.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    # 按键名，如 Enter, Tab, Escape, ArrowDown 等。
                    "description": "Key name, e.g. Enter, Tab, Escape, ArrowDown, etc.",
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
        # 对当前页面截图并保存到 workspace。返回与 display_image 工具等价的 Markdown 图片链接，前端可直接显示。
        "description": "Take a screenshot of the current page and save to workspace. Returns a Markdown image link equivalent to the display_image tool, displayable in the frontend.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    # 截图文件名（如 screenshot.png）。
                    "description": "Screenshot filename (e.g. screenshot.png).",
                },
                "full_page": {
                    "type": "boolean",
                    # 是否截取整页（包括滚动区域）。
                    "description": "Whether to capture full page (including scroll area).",
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
        # 提取指定元素的可见文本内容。
        "description": "Extract visible text content from a specified element.",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    # 元素的 @eN ref。
                    "description": "@eN ref of the element.",
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
        # 在浏览器页面上下文中执行 JavaScript 代码并返回结果。
        "description": "Execute JavaScript code in the browser page context and return the result.",
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
        # 等待页面条件就绪（网络空闲、特定文本/元素出现、URL 变化等）。
        "description": "Wait for page conditions to be ready (network idle, specific text/element appears, URL changes, etc.).",
        "parameters": {
            "type": "object",
            "properties": {
                "condition": {
                    "type": "string",
                    "enum": ["networkidle", "text", "url", "element"],
                    # 等待条件: networkidle(默认), text(文本出现), url(URL 匹配), element(元素出现)。
                    "description": "Wait condition: networkidle(default), text, url, element.",
                },
                "value": {
                    "type": "string",
                    # 条件值（text/url/element 时必填）。
                    "description": "Condition value (required for text/url/element).",
                },
                "timeout": {
                    "type": "integer",
                    # 超时秒数（默认 25）。
                    "description": "Timeout in seconds (default 25).",
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
        # 关闭当前浏览器会话，释放资源。
        "description": "Close the current browser session and release resources.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    handler=_handle_browser_close,
    emoji="🚪",
)