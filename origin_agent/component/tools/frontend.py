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
from system.sandbox import Access, SandboxError

logger = logging.getLogger(__name__)

# 从 filesystem 模块导入 sandbox 引用。
from .filesystem import _s as _get_sandbox


def _s():
    return _get_sandbox()


# ---------------------------------------------------------------------------
# 工具 handler
# ---------------------------------------------------------------------------


def _handle_validate_frontend(args: Dict[str, Any]) -> dict:
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
            timeout=120,
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
            valid=False, stage="install", error="Timeout after 120s",
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
            timeout=120,
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
            valid=False, stage="build", error="Timeout after 120s",
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
        # 验证前端代码：在目标前端目录中运行 ``pnpm install`` 和 ``pnpm run build``。
        # 在修改 ``frontend/`` 下任何文件（如 ``.tsx``、``.ts``、``.css``）之后、
        # 调用 ``evolve_code`` 之前使用此工具。
        # 可捕获 ``validate_code`` 无法检测的 TypeScript 和构建错误。
        # 默认路径为 ``fork:frontend``（进化目标）。
        "description": (
            "Validate frontend code: run ``pnpm install`` and "
            "``pnpm run build`` in the target frontend directory. "
            "Use this after modifying any file under ``frontend/`` "
            "(e.g. ``.tsx``, ``.ts``, ``.css``), before calling ``evolve_code``. "
            "Catches TypeScript and build errors that ``validate_code`` cannot detect.\n\n"
            "Default path is ``fork:frontend`` (evolution target)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    # 前端目录的逻辑路径（例如 'fork:frontend'）。默认 'fork:frontend'。
                    "description": (
                        "Logical path of the frontend directory (e.g. 'fork:frontend'). "
                        "Defaults to 'fork:frontend'."
                    ),
                },
            },
        },
    },
    handler=_handle_validate_frontend,
    emoji="🎨",
)