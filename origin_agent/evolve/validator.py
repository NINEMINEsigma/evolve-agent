"""代码验证器 — 对进化代码进行语法 + 导入检查。

使用 ``ast.parse()`` 快速检查语法，通过子进程运行 ``py_compile.compile()``
进行导入级验证。
"""

from __future__ import annotations

import ast
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def validate_syntax(file_path: Path) -> dict[str, Any]:
    """使用 ast.parse() 检查单个 Python 文件的语法错误。

    返回 ``{"status": "ok"}`` 或 ``{"status": "syntax_error", "line": ..., "message": ...}``。
    """
    try:
        source: str = file_path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(file_path))
        return {"file": file_path.name, "status": "ok"}
    except SyntaxError as exc:
        return {
            "file": file_path.name,
            "status": "syntax_error",
            "line": exc.lineno,
            "offset": exc.offset,
            "message": str(exc),
        }
    except FileNotFoundError:
        return {"file": file_path.name, "status": "error", "message": "File not found"}
    except Exception as exc:
        return {"file": file_path.name, "status": "error", "message": str(exc)}


def validate_compile(file_path: Path, timeout: int = 15) -> dict[str, Any]:
    """在子进程中通过 ``py_compile`` 检查 Python 文件能否编译。

    可捕获 ``ast.parse()`` 无法检测的导入级错误 —
    例如损坏的相对导入或缺失的依赖。

    返回 ``{"status": "ok"}`` 或 ``{"status": "compile_error", "message": ...}``。
    """
    code: str = (
        "import py_compile, sys; "
        f"py_compile.compile({file_path.as_posix()!r}, doraise=True)"
    )
    try:
        result: subprocess.CompletedProcess = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if result.returncode == 0:
            return {"file": file_path.name, "status": "ok"}
        return {
            "file": file_path.name,
            "status": "compile_error",
            "message": (result.stderr or result.stdout or "Unknown compile error").strip(),
        }
    except subprocess.TimeoutExpired:
        return {"file": file_path.name, "status": "error", "message": f"Compile timed out after {timeout}s"}
    except Exception as exc:
        return {"file": file_path.name, "status": "error", "message": str(exc)}


def validate_directory(
    dir_path: Path,
    *,
    deep: bool = False,
    timeout: int = 15,
) -> list[dict[str, Any]]:
    """验证目录中所有 .py 文件。

    *deep=False* — 仅语法检查（快速，覆盖大多数问题）。
    *deep=True* — 同时运行子进程 py_compile（较慢但更彻底）。

    返回每个文件的验证结果字典列表。
    """
    results: list[dict[str, Any]] = []
    if not dir_path.is_dir():
        return [{"file": str(dir_path), "status": "error", "message": "Not a directory"}]

    for py_file in sorted(dir_path.rglob("*.py")):
        # 跳过 __pycache__ 和其他生成目录
        if "__pycache__" in py_file.parts:
            continue
        result: dict[str, Any] = validate_syntax(py_file)
        results.append(result)
        if deep and result.get("status") == "ok":
            # 仅对通过语法检查的文件进行编译检查
            compile_result: dict[str, Any] = validate_compile(py_file, timeout=timeout)
            if compile_result["status"] != "ok":
                results[-1] = compile_result

    return results


def summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    """从验证结果生成高层摘要。

    返回 ``{"valid": bool, "total": int, "ok": int, "errors": int, "details": [...]}``。
    """
    ok: int = sum(1 for r in results if r.get("status") == "ok")
    errors: int = len(results) - ok
    if len(results) == 0:
        return {
            "valid": False,
            "total": 0,
            "ok": 0,
            "errors": 0,
            "details": [],
            "reason": "Fork directory is empty — no .py files found",
        }
    return {
        "valid": errors == 0,
        "total": len(results),
        "ok": ok,
        "errors": errors,
        "details": results,
    }