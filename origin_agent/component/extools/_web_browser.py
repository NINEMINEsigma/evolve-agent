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
from entity.constant import SUBPROCESS_SHORT_TIMEOUT_DEFAULT, STATIC_FILE_HTTP_PREFIX

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
        logger.warning("agent-browser binary lookup via pnpm exec failed: %s", exc, exc_info=True)

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
            logger.warning("shutil.which lookup failed for %s", name, exc_info=True)

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
        logger.warning("agent-browser binary lookup via pnpm bin -g failed: %s", exc, exc_info=True)

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
        logger.warning("agent-browser binary lookup via npx --no-install failed: %s", exc, exc_info=True)

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
            agentspace = sb.agentspace
            fs_path = (agentspace / rel.replace("/", "\\")).resolve()
            fs_path.parent.mkdir(parents=True, exist_ok=True)
            return fs_path, rel
        except Exception:
            logger.warning("Failed to resolve ws: path for browser output: %s", rel, exc_info=True)
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

        md_link = f"![screenshot]({STATIC_FILE_HTTP_PREFIX}/{rel_path})"
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
        # 获取当前页面的交互元素树（含 @eN ref）。
        #
        # ## 前置条件
        # 必须先调用 browser_navigate 打开页面。
        #
        # ## 调用效果
        # 返回当前页面 DOM 的交互元素树，元素以 @eN 形式引用，供 click/fill/type 等工具使用。
        # 页面发生变化后应重新调用以获取最新状态。
        #
        # ## 返回
        # ```json
        # {"snapshot": "...", "instruction": "Use @eN ref to interact with elements (e.g. browser_click @e3). Re-snapshot after page changes."}
        # ```
        #
        # ## 何时使用
        # - 页面加载后确认可用元素。
        # - 执行点击、填写等操作后确认页面新状态。
        # - 需要查找特定元素或文本时。
        #
        # ## 副作用/注意
        # - 默认只展开 4 层深度；复杂页面可设置 full=true 获取完整树。
        # - 快照不包含不可见或不可交互元素。
        "description": """Get the interactive element tree (@eN ref) of the current page.

## Prerequisites
A page must have been opened via browser_navigate first.

## Effect
Returns the current page DOM as an interactive element tree. Elements are referenced as @eN and can be used by click/fill/type tools. Re-snapshot after page changes to see the latest state.

## Returns
```json
{"snapshot": "...", "instruction": "Use @eN ref to interact with elements (e.g. browser_click @e3). Re-snapshot after page changes."}
```

## When to Use
- Confirm available elements after a page loads.
- Check the new page state after clicks, fills, or other interactions.
- Search for a specific element or text.

## Side Effects / Notes
- Default depth is limited to 4 levels; set full=true for the complete tree on complex pages.
- The snapshot does not include hidden or non-interactive elements.""",
        "parameters": {
            "type": "object",
            "properties": {
                "full": {
                    "type": "boolean",
                    # 是否获取完整深度的元素树（默认只展开 4 层）。
                    "description": """Set to true to capture the full element tree depth (default is limited to 4 levels).""",
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
        # 点击页面上的指定元素。
        #
        # ## 前置条件
        # 页面必须通过 browser_navigate 打开，且目标元素必须出现在最近的 browser_snapshot 中。
        #
        # ## 调用效果
        # 点击 @eN ref 或 CSS selector 指定的元素，点击后自动重新抓取页面快照返回最新状态。
        #
        # ## 返回
        # ```json
        # {"clicked": "@e3", "snapshot": "...", "instruction": "Element clicked, current page state shown in snapshot."}
        # ```
        #
        # ## 何时使用
        # - 点击按钮、链接、复选框等交互元素。
        # - 提交表单前的操作。
        #
        # ## 副作用/注意
        # - 可能触发页面跳转、弹窗或加载新内容。
        # - 点击后应检查返回的 snapshot 确认结果。
        # - ref 和 selector 二选一，不能同时为空。
        "description": """Click a page element by @eN ref or CSS selector.

## Prerequisites
A page must have been opened via browser_navigate, and the target element must appear in a recent browser_snapshot.

## Effect
Clicks the element identified by @eN ref or CSS selector, then automatically re-captures a page snapshot and returns the latest state.

## Returns
```json
{"clicked": "@e3", "snapshot": "...", "instruction": "Element clicked, current page state shown in snapshot."}
```

## When to Use
- Click buttons, links, checkboxes, or other interactive elements.
- Perform actions before form submission.

## Side Effects / Notes
- May trigger page navigation, pop-ups, or new content loading.
- Inspect the returned snapshot to confirm the result.
- Provide either ref or selector; at least one is required.""",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    # 元素的 @eN 引用（例如 @e3），来自 browser_navigate 或 browser_snapshot。
                    "description": """@eN ref of the element (e.g. @e3), from browser_navigate or browser_snapshot.""",
                },
                "selector": {
                    "type": "string",
                    # 当 ref 不可用时使用的 CSS 选择器。
                    "description": """CSS selector to use when ref is not available.""",
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
        #
        # ## 前置条件
        # 页面必须通过 browser_navigate 打开，且目标输入框必须出现在最近的 browser_snapshot 中。
        #
        # ## 调用效果
        # 先清除元素现有内容，再填入 text 参数指定的文本。适用于表单输入。
        #
        # ## 返回
        # ```json
        # {"filled": "@e3", "value": "hello", "message": "Input field filled."}
        # ```
        #
        # ## 何时使用
        # - 需要替换输入框现有内容时。
        # - 填写用户名、搜索框等单行文本字段。
        #
        # ## 副作用/注意
        # - 会覆盖元素原有内容。
        # - 调用后通常需要配合 browser_click 或 browser_press_key 提交。
        "description": """Clear an input field and fill it with the specified text.

## Prerequisites
A page must have been opened via browser_navigate, and the target input field must appear in a recent browser_snapshot.

## Effect
Clears the element's existing content and enters the text provided in the text parameter. Suitable for form input.

## Returns
```json
{"filled": "@e3", "value": "hello", "message": "Input field filled."}
```

## When to Use
- Replace the existing content of an input field.
- Fill single-line text fields such as usernames or search boxes.

## Side Effects / Notes
- Overwrites the element's previous content.
- Usually followed by browser_click or browser_press_key to submit the form.""",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    # 输入框的 @eN 引用。
                    "description": """@eN ref of the input field.""",
                },
                "text": {
                    "type": "string",
                    # 要填入的文本。
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
        # 在输入框中逐字符输入文本（不清除现有内容）。
        #
        # ## 前置条件
        # 页面必须通过 browser_navigate 打开，且目标输入框必须出现在最近的 browser_snapshot 中。
        #
        # ## 调用效果
        # 将 text 追加到输入框现有内容之后；不传 text 时仅聚焦该元素。
        #
        # ## 返回
        # ```json
        # {"typed": "@e3", "value": "hello", "message": "Input complete."}
        # ```
        #
        # ## 何时使用
        # - 需要在现有内容后追加文本时。
        # - 模拟逐字输入行为。
        # - 需要仅聚焦某个输入框时（text 留空）。
        #
        # ## 副作用/注意
        # - 不会清除元素原有内容；如需替换，请使用 browser_fill。
        # - 某些动态搜索框可能需要使用 browser_type 而非 browser_fill。
        "description": """Type text character by character into an input field without clearing existing content.

## Prerequisites
A page must have been opened via browser_navigate, and the target input field must appear in a recent browser_snapshot.

## Effect
Appends the provided text to the input field's existing content. If text is omitted, the element is only focused.

## Returns
```json
{"typed": "@e3", "value": "hello", "message": "Input complete."}
```

## When to Use
- Append text after existing content.
- Simulate realistic typing behavior.
- Focus an input field without changing its value (leave text empty).

## Side Effects / Notes
- Does not clear existing content; use browser_fill if replacement is needed.
- Some dynamic search boxes may require browser_type instead of browser_fill.""",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    # 输入框的 @eN 引用。
                    "description": """@eN ref of the input field.""",
                },
                "text": {
                    "type": "string",
                    # 要输入的文本；留空则仅聚焦元素。
                    "description": """Text to type. Leave empty to focus the element only.""",
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
        # 向页面发送键盘按键。
        #
        # ## 前置条件
        # 页面必须通过 browser_navigate 打开。
        #
        # ## 调用效果
        # 模拟按下指定按键，常用于表单提交、选择下拉项、关闭弹窗等。
        # 按键后自动重新抓取页面快照。
        #
        # ## 返回
        # ```json
        # {"key": "Enter", "snapshot": "...", "instruction": "Key Enter sent."}
        # ```
        #
        # ## 何时使用
        # - 填写表单后按 Enter 提交。
        # - 触发键盘快捷键。
        # - 在焦点元素上按 Tab、Escape、ArrowDown 等导航键。
        #
        # ## 副作用/注意
        # - 页面焦点位置会影响按键效果。
        # - 可能触发页面跳转或弹窗。
        "description": """Send a keyboard key to the page.

## Prerequisites
A page must have been opened via browser_navigate.

## Effect
Simulates pressing the specified key. Commonly used for form submission, selecting dropdown items, or dismissing dialogs. A fresh snapshot is captured automatically after the key press.

## Returns
```json
{"key": "Enter", "snapshot": "...", "instruction": "Key Enter sent."}
```

## When to Use
- Press Enter to submit a form after filling it.
- Trigger keyboard shortcuts.
- Press Tab, Escape, ArrowDown, or other navigation keys on the focused element.

## Side Effects / Notes
- The effect depends on the current page focus.
- May trigger navigation or pop-ups.""",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    # 按键名称，例如 Enter、Tab、Escape、ArrowDown 等。
                    "description": """Key name, e.g. Enter, Tab, Escape, ArrowDown.""",
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
        # 对当前页面截图并保存到工作空间。
        #
        # ## 前置条件
        # 页面必须通过 browser_navigate 打开。
        #
        # ## 调用效果
        # 截取当前浏览器页面，保存为 PNG 文件到 ws:browser/，返回 Markdown 图片链接和逻辑路径。
        #
        # ## 返回
        # ```json
        # {"path": "ws:browser/screenshot.png", "markdown": "![screenshot](/uploads/browser/screenshot.png)", "message": "Screenshot saved: ws:browser/screenshot.png"}
        # ```
        #
        # ## 何时使用
        # - 保存页面视觉状态。
        # - 向用户展示当前页面内容。
        # - 记录自动化执行结果。
        #
        # ## 副作用/注意
        # - 生成图片文件并写入工作空间。
        # - 截图默认视口；设置 full_page=true 可截取整个滚动区域。
        "description": """Take a screenshot of the current page and save it to the workspace.

## Prerequisites
A page must have been opened via browser_navigate.

## Effect
Captures the current browser page and saves it as a PNG file under ws:browser/. Returns a Markdown image link and the logical path.

## Returns
```json
{"path": "ws:browser/screenshot.png", "markdown": "![screenshot](/uploads/browser/screenshot.png)", "message": "Screenshot saved: ws:browser/screenshot.png"}
```

## When to Use
- Save the visual state of a page.
- Show the current page content to the user.
- Record the result of an automation step.

## Side Effects / Notes
- Creates an image file and writes it to the workspace.
- Captures the visible viewport by default; set full_page=true to capture the full scrollable area.""",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    # 截图文件名（例如 screenshot.png）。
                    "description": """Screenshot filename (e.g. screenshot.png).""",
                },
                "full_page": {
                    "type": "boolean",
                    # 是否截取完整页面（包括滚动区域）。
                    "description": """Whether to capture the full page including the scrollable area.""",
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
        # 提取指定可见元素的文本内容。
        #
        # ## 前置条件
        # 页面必须通过 browser_navigate 打开，且目标元素必须出现在最近的 browser_snapshot 中。
        #
        # ## 调用效果
        # 返回 @eN ref 指定元素的可见文本内容。
        #
        # ## 返回
        # ```json
        # {"text": "Extracted visible text"}
        # ```
        #
        # ## 何时使用
        # - 获取按钮、标签、段落等具体文本。
        # - 验证页面内容。
        #
        # ## 副作用/注意
        # - 仅返回可见文本，隐藏元素可能为空。
        # - 获取大量文本时建议使用 browser_snapshot 或 browser_eval。
        "description": """Extract the visible text content of a specified element.

## Prerequisites
A page must have been opened via browser_navigate, and the target element must appear in a recent browser_snapshot.

## Effect
Returns the visible text of the element identified by the @eN ref.

## Returns
```json
{"text": "Extracted visible text"}
```

## When to Use
- Retrieve the text of a button, label, paragraph, or other element.
- Verify page content.

## Side Effects / Notes
- Only visible text is returned; hidden elements may yield empty strings.
- For larger text extraction, consider browser_snapshot or browser_eval.""",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    # 目标元素的 @eN 引用。
                    "description": """@eN ref of the target element.""",
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
        # 在页面上下文中执行 JavaScript 代码并返回结果。
        #
        # ## 前置条件
        # 页面必须通过 browser_navigate 打开。
        # 需要具备目标页面 DOM 的基本知识。
        #
        # ## 调用效果
        # 将 code 作为 JavaScript 在页面中执行，并返回字符串化后的结果。
        # 可用于读取页面状态、操作 DOM、触发事件等高级场景。
        #
        # ## 返回
        # ```json
        # {"result": "..."}
        # ```
        #
        # ## 何时使用
        # - browser_snapshot 无法获取所需信息时。
        # - 需要执行自定义 DOM 查询或操作时。
        # - 触发页面内部函数或读取 JS 变量。
        #
        # ## 副作用/注意
        # - 执行的代码可能影响页面状态，请谨慎使用。
        # - 返回结果会被 trim 处理。
        # - 跨域限制和安全策略可能导致部分代码执行失败。
        "description": """Execute JavaScript code in the browser page context and return the result.

## Prerequisites
A page must have been opened via browser_navigate. Basic knowledge of the target page DOM is required.

## Effect
Executes the provided code as JavaScript in the page and returns the stringified result. Useful for reading page state, manipulating the DOM, or triggering events.

## Returns
```json
{"result": "..."}
```

## When to Use
- When browser_snapshot does not expose the needed information.
- When custom DOM queries or manipulations are required.
- To trigger page-internal functions or read JS variables.

## Side Effects / Notes
- Executed code may alter page state; use with caution.
- The returned result is trimmed.
- Cross-origin restrictions and security policies may cause some code to fail.""",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    # 要执行的 JavaScript 代码，支持多行。
                    "description": """JavaScript code to execute. Supports multiple lines.""",
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
        # 等待页面条件满足后再继续。
        #
        # ## 前置条件
        # 页面必须通过 browser_navigate 打开。
        #
        # ## 调用效果
        # 等待指定条件成立：networkidle（网络空闲，默认）、text（出现指定文本）、url（URL 匹配）、element（元素出现）。
        # 条件满足后返回最新页面快照。
        #
        # ## 返回
        # ```json
        # {"snapshot": "...", "message": "Wait complete, page ready."}
        # ```
        #
        # ## 何时使用
        # - 页面加载动态内容后等待其渲染完成。
        # - 等待特定文本或元素出现。
        # - 等待网络请求完成。
        #
        # ## 副作用/注意
        # - 等待超时默认 25 秒，超时会导致调用失败。
        # - condition=text/url/element 时需要同时提供 value。
        "description": """Wait for a page condition to be ready.

## Prerequisites
A page must have been opened via browser_navigate.

## Effect
Waits until the specified condition is met: networkidle (default), text (specified text appears), url (URL matches), or element (element appears). Returns a fresh page snapshot once the condition is satisfied.

## Returns
```json
{"snapshot": "...", "message": "Wait complete, page ready."}
```

## When to Use
- Wait for dynamic content to finish rendering after navigation.
- Wait for specific text or an element to appear.
- Wait for network requests to settle.

## Side Effects / Notes
- Default timeout is 25 seconds; exceeding it causes the call to fail.
- condition=text/url/element requires the value parameter to be provided.""",
        "parameters": {
            "type": "object",
            "properties": {
                "condition": {
                    "type": "string",
                    "enum": ["networkidle", "text", "url", "element"],
                    # 等待条件：networkidle（默认）、text、url、element。
                    "description": """Wait condition: networkidle (default), text, url, or element.""",
                },
                "value": {
                    "type": "string",
                    # 条件值。condition 为 text/url/element 时必填。
                    "description": """Condition value. Required when condition is text, url, or element.""",
                },
                "timeout": {
                    "type": "integer",
                    # 超时秒数，默认 25。
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
        # 关闭当前浏览器会话并释放资源。
        #
        # ## 前置条件
        # 浏览器会话已通过 browser_navigate 启动。
        #
        # ## 调用效果
        # 关闭浏览器进程，释放系统资源。关闭后所有页面状态丢失。
        #
        # ## 返回
        # ```json
        # {"message": "Browser session closed."}
        # ```
        #
        # ## 何时使用
        # - 浏览器自动化任务结束时。
        # - 需要释放内存或避免浏览器长时间占用资源时。
        #
        # ## 副作用/注意
        # - 关闭后会话完全终止，未保存的页面状态无法恢复。
        # - 后续如需再次使用浏览器，必须重新调用 browser_navigate。
        "description": """Close the current browser session and release resources.

## Prerequisites
A browser session must have been started via browser_navigate.

## Effect
Closes the browser process and frees system resources. All page state is lost.

## Returns
```json
{"message": "Browser session closed."}
```

## When to Use
- At the end of a browser automation workflow.
- When memory needs to be freed or the browser should not remain open.

## Side Effects / Notes
- The session is completely terminated; unsaved page state cannot be recovered.
- To use the browser again, call browser_navigate to start a new session.""",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    handler=_handle_browser_close,
    emoji="🚪",
)