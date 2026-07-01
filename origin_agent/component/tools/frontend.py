"""前端验证工具 — 验证进化的前端代码能否构建。

模块导入时通过 ``registry.register()`` 注册。
在目标前端目录（默认 fast 模式下为 ``fork:frontend``）中
运行 ``pnpm install`` 和 ``pnpm run build``，
以在进化交换前捕获 TypeScript 或构建错误。
"""

from __future__ import annotations

import logging
import subprocess  # nosec
import sys
from typing import Any, Dict

from abstract.tools.registry import registry, tool_error, tool_result
from entity.constant import SUBPROCESS_TIMEOUT_DEFAULT
from entity.puretype import ToolAvailability
from system.sandbox import Access, SandboxError

logger = logging.getLogger(__name__)

# 从 filesystem 模块导入 sandbox 引用。
from .filesystem import _s as _get_sandbox


def _s():
    return _get_sandbox()


# ---------------------------------------------------------------------------
# 工具 handler
# ---------------------------------------------------------------------------


def _handle_validate_frontend(args: dict[str, Any]) -> dict:
    """通过运行 pnpm install && pnpm run build 验证前端代码。

    预期参数：
        path: str — 前端目录的逻辑路径
                    （fast 模式默认 "fork:frontend"）。
    """
    path: str = str(args.get("path", "")).strip()

    # ---- 解析目标目录 ----
    if not path:
        path = "fork:frontend"

    resolved: Any
    try:
        if ":" in path:
            resolved = _s().resolve(path, Access.READ)
        else:
            resolved = _s().resolve(f"fork:{path}", Access.READ)
        frontend_dir: Any = resolved.real
    except (SandboxError, FileNotFoundError) as exc:
        return tool_error(str(exc), path=path)

    if not frontend_dir.is_dir():
        return tool_error(f"Not a directory: {frontend_dir}", path=path)

    pkg_json: Any = frontend_dir / "package.json"
    if not pkg_json.exists():
        return tool_error("No package.json found in frontend directory", path=path)

    pnpm: str = "pnpm.cmd" if sys.platform == "win32" else "pnpm"
    # 强制非交互模式：避免 pnpm 在子进程中弹出 ConfirmPrompt 导致 readline 崩溃
    import os
    pnpm_env: dict[str, str] = {**os.environ, "CI": "true"}

    # ---- pnpm install ----
    logger.info("validate_frontend | install | cwd=%s", frontend_dir)
    try:
        install_proc: subprocess.CompletedProcess = subprocess.run(
            [pnpm, "install"],
            cwd=str(frontend_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=SUBPROCESS_TIMEOUT_DEFAULT,
            env=pnpm_env,
        )
        if install_proc.returncode != 0:
            return tool_result(
                valid=False,
                stage="install",
                exit_code=install_proc.returncode,
                stdout=_truncate(install_proc.stdout),
                stderr=_truncate(install_proc.stderr),
                hint=(
                    "pnpm install failed. Check dependency conflicts, "
                    "lock file corruption, or missing peer dependencies."
                ),
            )
    except subprocess.TimeoutExpired:
        return tool_result(
            valid=False, stage="install", error=f"Timeout after {SUBPROCESS_TIMEOUT_DEFAULT}s",
        )
    except Exception as exc:
        return tool_result(
            valid=False, stage="install", error=str(exc),
        )

    # ---- pnpm run build ----
    logger.info("validate_frontend | build | cwd=%s", frontend_dir)
    try:
        build_proc: subprocess.CompletedProcess = subprocess.run(
            [pnpm, "run", "build"],
            cwd=str(frontend_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=SUBPROCESS_TIMEOUT_DEFAULT,
            env=pnpm_env,
        )
        if build_proc.returncode != 0:
            return tool_result(
                valid=False,
                stage="build",
                exit_code=build_proc.returncode,
                stdout=_truncate(build_proc.stdout),
                stderr=_truncate(build_proc.stderr),
                hint=(
                    "Frontend build failed. Check TypeScript errors, "
                    "missing imports, or build configuration issues."
                ),
            )
    except subprocess.TimeoutExpired:
        return tool_result(
            valid=False, stage="build", error=f"Timeout after {SUBPROCESS_TIMEOUT_DEFAULT}s",
        )
    except Exception as exc:
        return tool_result(
            valid=False, stage="build", error=str(exc),
        )

    # 构建成功 — 将输出尾打入日志供诊断
    build_tail: str = _tail(build_proc.stdout, 8)
    logger.info("Frontend build output (tail):\n%s", build_tail)

    return tool_result(
        valid=True,
        stage="build",
        exit_code=0,
        build_output=build_tail,
        message="Frontend validation passed: install + build successful.",
    )


def _truncate(text: str | None, limit: int = 2000) -> str:
    """返回 *text* 的尾部，最多 *limit* 个字符。"""
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return "..." + text[-limit:]


def _tail(text: str | None, n: int = 8) -> str:
    """返回 *text* 的最后 *n* 行。"""
    if not text:
        return "(empty)"
    lines: list[str] = text.strip().split("\n")
    return "\n".join(lines[-n:])


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

registry.register(
    name="validate_frontend",
    toolset="frontend",
    schema={
        # 验证前端代码能否构建。在 fork:frontend 目录下运行 pnpm install && pnpm run build。
        # 前置条件：已通过 write_fork 修改了 frontend/ 下的 .tsx/.ts/.css 文件。仅 fast 模式下可用。
        # path 默认 'fork:frontend'（进化目标目录）。可指定其他逻辑路径。
        # 调用效果：在目标目录中执行 pnpm install 和 pnpm run build（CI=true 非交互模式），捕获 TypeScript 和构建错误。
        # 成功返回：{ valid: true, stage: "build", exit_code: 0, build_output, message }
        # 失败返回：{ valid: false, stage: "install"|"build", exit_code, stdout?, stderr?, hint? } 或 { valid: false, stage: ..., error }
        # 典型场景：修改前端文件后、evolve_code 前调用，捕获 validate_code 无法检测的 TypeScript/构建错误。
        # 注意：运行时间较长（超时时间 SUBPROCESS_TIMEOUT_DEFAULT），非前端修改无需调用。
        "description": """Validate frontend code by running `pnpm install && pnpm run build` in the target frontend directory.

## Prerequisites
- Frontend files (`.tsx`, `.ts`, `.css`) have been modified via `write_fork`.
- Only available in fast mode.

## Effect
Runs `pnpm install` followed by `pnpm run build` in the target directory (non-interactive, `CI=true`). Catches TypeScript and build errors that `validate_code` cannot detect. Does not modify any files beyond what pnpm itself generates (`node_modules/`, `dist/`).

## Parameters
- `path` (string, default `"fork:frontend"`): Logical path of the frontend directory. Can be a bare name or a namespaced path like `"fork:frontend"`.

## Returns
**Success**:
```json
{ "valid": true, "stage": "build", "exit_code": 0, "build_output": "<tail of build output>", "message": "Frontend validation passed..." }
```
**Install failure**:
```json
{ "valid": false, "stage": "install", "exit_code": N, "stdout": "...", "stderr": "...", "hint": "pnpm install failed. Check dependency conflicts..." }
```
**Build failure**:
```json
{ "valid": false, "stage": "build", "exit_code": N, "stdout": "...", "stderr": "...", "hint": "Frontend build failed. Check TypeScript errors..." }
```
**Timeout**:
```json
{ "valid": false, "stage": "install"|"build", "error": "Timeout after Ns" }
```

## When to Use
Evolution workflow — call after modifying frontend files and before `evolve_code`. Skip if no frontend files were changed.

## Side Effects
Creates `node_modules/` and `dist/` in the target directory. Long-running (up to timeout); only call when frontend changes were actually made.""",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # 前端目录的逻辑路径。默认 'fork:frontend'（进化目标）。可为裸名或命名空间路径。
                    "description": """Logical path of the frontend directory. Defaults to 'fork:frontend' (evolution target). Can be a bare name or namespaced path.""",
                },
            },
        },
    },
    handler=_handle_validate_frontend,
    emoji="🎨",
    availability=ToolAvailability.MAIN,
)