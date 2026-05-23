"""Code validator — syntax + import checks for evolved code.

Uses ``ast.parse()`` for fast syntax checking and ``py_compile.compile()``
(via subprocess) for import-level validation.
"""

from __future__ import annotations

import ast
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def validate_syntax(file_path: Path) -> Dict[str, Any]:
    """Check a single Python file for syntax errors using ast.parse().

    Returns ``{"status": "ok"}`` or ``{"status": "syntax_error", "line": ..., "message": ...}``.
    """
    try:
        source = file_path.read_text(encoding="utf-8")
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


def validate_compile(file_path: Path, timeout: int = 15) -> Dict[str, Any]:
    """Check if a Python file can be compiled via ``py_compile`` in a subprocess.

    This catches import-level errors that ``ast.parse()`` cannot —
    for example, broken relative imports or missing dependencies.

    Returns ``{"status": "ok"}`` or ``{"status": "compile_error", "message": ...}``.
    """
    code = (
        "import py_compile, sys; "
        f"py_compile.compile({str(file_path)!r}, doraise=True)"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
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
) -> List[Dict[str, Any]]:
    """Validate all .py files in a directory.

    *deep=False* — syntax check only (fast, catches most issues).
    *deep=True* — also runs py_compile in a subprocess (slower but more thorough).

    Returns a list of per-file result dicts.
    """
    results: List[Dict[str, Any]] = []
    if not dir_path.is_dir():
        return [{"file": str(dir_path), "status": "error", "message": "Not a directory"}]

    for py_file in sorted(dir_path.rglob("*.py")):
        # Skip __pycache__ and other generated dirs
        if "__pycache__" in py_file.parts:
            continue
        result = validate_syntax(py_file)
        results.append(result)
        if deep and result.get("status") == "ok":
            # Only compile-check files that pass syntax
            compile_result = validate_compile(py_file, timeout=timeout)
            if compile_result["status"] != "ok":
                results[-1] = compile_result

    return results


def summary(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate a high-level summary from validation results.

    Returns ``{"valid": bool, "total": int, "ok": int, "errors": int, "details": [...]}``.
    """
    ok = sum(1 for r in results if r.get("status") == "ok")
    errors = len(results) - ok
    return {
        "valid": errors == 0,
        "total": len(results),
        "ok": ok,
        "errors": errors,
        "details": results,
    }