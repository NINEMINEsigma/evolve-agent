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
from component.tools.filesystem import _s as _get_sandbox
from entity.constant import SUBPROCESS_SHORT_TIMEOUT_DEFAULT

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
            capture_output=True, text=True, timeout=SUBPROCESS_SHORT_TIMEOUT_DEFAULT,
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
            capture_output=True, text=True, timeout=SUBPROCESS_SHORT_TIMEOUT_DEFAULT,
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


def _handle_browser_navigate(args: dict[str, Any]) -> dict:
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


def _handle_browser_snapshot(args: dict[str, Any]) -> dict:
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


def _handle_browser_click(args: dict[str, Any]) -> dict:
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


def _handle_browser_fill(args: dict[str, Any]) -> dict:
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


def _handle_browser_type(args: dict[str, Any]) -> dict:
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


def _handle_browser_press_key(args: dict[str, Any]) -> dict:
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


def _handle_browser_screenshot(args: dict[str, Any]) -> dict:
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


def _handle_browser_get_text(args: dict[str, Any]) -> dict:
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


def _handle_browser_eval(args: dict[str, Any]) -> dict:
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


def _handle_browser_wait(args: dict[str, Any]) -> dict:
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


def _handle_browser_close(args: dict[str, Any]) -> dict:
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
        # 在浏览器中打开指定 URL 并返回当前页面的交互元素快照。
        # ⚠️ 这是所有浏览器自动化工具的**关键起点**，必须先调用此工具打开页面，
        # 才能使用 browser_click、browser_fill、browser_screenshot 等其他浏览器工具。
        # 需要 agent-browser CLI 已安装（pnpm i -g agent-browser && agent-browser install）。
        # 首次调用会启动浏览器会话，后续工具共享同一会话（session name: evolve）。
        #
        # ## 前置条件
        # - agent-browser CLI 必须已安装。
        # - URL 必须以 http:// 或 https:// 开头。
        #
        # ## 调用效果
        # 打开 URL 后获取页面交互元素树（含 @eN ref），用于后续点击、填写等操作。
        # 会话在 browser_close 之前保持活跃。
        #
        # ## 返回
        # ```json
        # {"url": "https://example.com", "snapshot": "...", "instruction": "Page loaded. Use browser_snapshot for latest state, use @eN ref to interact with elements."}
        # ```
        #
        # ## 何时使用
        # - 开始浏览器自动化流程时**第一步**调用。
        # - 跳转到新的页面 URL。
        #
        # ## 副作用/注意
        # - 首次调用会启动浏览器进程，可能耗时数秒。
        # - 会话持续占用系统资源，直到调用 browser_close。
        # - 页面打不开或超时时，可能是需要鉴权登录（如 SSO、OAuth、Cookie 认证），
        #   此时应改用 web_fetch 获取内容，或提示用户手动完成登录后再继续。
        "description": """Open a URL in the browser and return a snapshot of interactive elements. This is the **critical starting point** for all browser automation tools — you must call this first before using browser_click, browser_fill, browser_screenshot, etc. Requires agent-browser CLI to be installed.

## Prerequisites
- agent-browser CLI must be installed (pnpm i -g agent-browser && agent-browser install).
- The URL must start with http:// or https://.

## Effect
Opens the URL and captures the interactive element tree (with @eN refs) for subsequent click/fill/type operations. The session remains active until browser_close is called.

## Returns
```json
{"url": "https://example.com", "snapshot": "...", "instruction": "Page loaded. Use browser_snapshot for latest state, use @eN ref to interact with elements."}
```

## When to Use
- **First step** when starting a browser automation workflow.
- Navigate to a new page URL.

## Side Effects / Notes
- The first call launches the browser process, which may take a few seconds.
- The session consumes system resources until browser_close is called.
- If the page fails to load or times out, it may require authentication (e.g. SSO, OAuth, cookie-based login). In such cases, use web_fetch instead, or ask the user to complete login manually before continuing.""",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    # 要打开的完整 URL（包含 https://）。
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
        # Get the interactive element tree (@eN ref) of the current page to understand page state.
        "description": """Get the interactive element tree (@eN ref) of the current page to understand page state.""",
        "parameters": {
            "type": "object",
            "properties": {
                "full": {
                    "type": "boolean",
                    # Set to true for full depth (default limited to 4 levels).
                    "description": """Set to true for full depth (default limited to 4 levels).""",
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
        # Click a page element via @eN ref or CSS selector. Auto-snapshots after click returning latest state.
        "description": """Click a page element via @eN ref or CSS selector. Auto-snapshots after click returning latest state.""",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    # @eN ref of the element (e.g. @e3), from browser_navigate or browser_snapshot.
                    "description": """@eN ref of the element (e.g. @e3), from browser_navigate or browser_snapshot.""",
                },
                "selector": {
                    "type": "string",
                    # CSS selector (used when ref is not available).
                    "description": """CSS selector (used when ref is not available).""",
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
        # Clear the input field and fill with specified text.
        "description": """Clear the input field and fill with specified text.""",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    # @eN ref of the input field.
                    "description": """@eN ref of the input field.""",
                },
                "text": {
                    "type": "string",
                    # Text to fill in.
                    "description": """Text to fill in.""",
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
        # Type text character by character into an input field (does not clear existing content). Without text, just focuses the element.
        "description": """Type text character by character into an input field (does not clear existing content). Without text, just focuses the element.""",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    # @eN ref of the input field.
                    "description": """@eN ref of the input field.""",
                },
                "text": {
                    "type": "string",
                    # Text to type (optional, leave empty to focus).
                    "description": """Text to type (optional, leave empty to focus).""",
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
        # Send keyboard keys (Enter, Tab, Escape, ArrowDown, etc.). Typically used for form submission or navigation.
        "description": """Send keyboard keys (Enter, Tab, Escape, ArrowDown, etc.). Typically used for form submission or navigation.""",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    # Key name, e.g. Enter, Tab, Escape, ArrowDown, etc.
                    "description": """Key name, e.g. Enter, Tab, Escape, ArrowDown, etc.""",
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
        # Take a screenshot of the current page and save to workspace. Returns a Markdown image link equivalent to the display_image tool, displayable in the frontend.
        "description": """Take a screenshot of the current page and save to workspace. Returns a Markdown image link equivalent to the display_image tool, displayable in the frontend.""",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    # Screenshot filename (e.g. screenshot.png).
                    "description": """Screenshot filename (e.g. screenshot.png).""",
                },
                "full_page": {
                    "type": "boolean",
                    # Whether to capture full page (including scroll area).
                    "description": """Whether to capture full page (including scroll area).""",
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
        # Extract visible text content from a specified element.
        "description": """Extract visible text content from a specified element.""",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    # @eN ref of the element.
                    "description": """@eN ref of the element.""",
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
        # Execute JavaScript code in the browser page context and return the result.
        "description": """Execute JavaScript code in the browser page context and return the result.""",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    # JavaScript code to execute. Supports multiple lines.
                    "description": """要执行的 JavaScript 代码。支持多行。""",
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
        # Wait for page conditions to be ready (network idle, specific text/element appears, URL changes, etc.).
        "description": """Wait for page conditions to be ready (network idle, specific text/element appears, URL changes, etc.).""",
        "parameters": {
            "type": "object",
            "properties": {
                "condition": {
                    "type": "string",
                    "enum": ["networkidle", "text", "url", "element"],
                    # Wait condition: networkidle(default), text, url, element.
                    "description": """Wait condition: networkidle(default), text, url, element.""",
                },
                "value": {
                    "type": "string",
                    # Condition value (required for text/url/element).
                    "description": """Condition value (required for text/url/element).""",
                },
                "timeout": {
                    "type": "integer",
                    # Timeout in seconds (default 25).
                    "description": """Timeout in seconds (default 25).""",
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
        # Close the current browser session and release resources.
        "description": """Close the current browser session and release resources.""",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    handler=_handle_browser_close,
    emoji="🚪",
)