"""Diff 工具集 — 多维度代码对比。

每个对比维度以独立工具注册；核心差异算法由 ``_compare_dirs()`` 统一实现。

工具清单
========
=============== =================================== =================
工具名          左侧                                右侧
=============== =================================== =================
diff_origin_fast origin_agent/                       fast_agent_space/
diff_fast_fork   fast_agent_space/                   fork（slow 目录）
=============== =================================== =================

路径推导
=======
- ``_FAST_ROOT``：从 ``__file__`` 上溯 3 层得到 fast_agent_space/
- ``_ORIGIN_ROOT``：从 fast 上溯到项目根 → origin_agent/
- ``_FORK_ROOT``：通过 sandbox resolve("fork:", READ) 获取
"""

from __future__ import annotations

import difflib
import fnmatch
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

from abstract.tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 路径推导
# ---------------------------------------------------------------------------
# <project_root>/
#   origin_agent/
#   workspace/
#     fast_agent_space/   ← 当前运行副本（本文件所在）
#       component/extools/diff_tools.py
#     slow_agent_space/   ← 进化目标目录（fork）

# Warning: _FAST_ROOT 和 _ORIGIN_ROOT 在模块导入时固化，整个 agent 生命周期内
# 不会更新。当前架构下每个 agent 进程只运行一次（进化交换后会重启进程），
# 因此不存在路径过时的问题。若将来引入热重载（进程不重启），需要将这些
# 路径改为懒加载函数。
_FAST_ROOT: Path = Path(__file__).resolve().parent.parent.parent
_ORIGIN_ROOT: Path = _FAST_ROOT.parent.parent / "origin_agent"


def _resolve_fork_root() -> Path | None:
    """通过 sandbox 获取 fork（slow）目录的绝对路径。"""
    try:
        from component.tools.filesystem import _s as _get_sandbox
        r = _get_sandbox().resolve("fork:", "read")
        return r.real
    except Exception as exc:
        logger.debug("Could not resolve fork: sandbox — %s", exc)
        # fallback：默认 slow_agent_space/
        fallback = _FAST_ROOT.parent.parent / "slow_agent_space"
        if fallback.is_dir():
            return fallback
        return None


# ---------------------------------------------------------------------------
# 跳过规则
# ---------------------------------------------------------------------------

_SKIP_DIRS: frozenset[str] = frozenset({
    "__pycache__", ".git", ".svn",
    "node_modules", ".pnpm-store",
    "dist", ".vite", ".cache",
    ".mypy_cache", ".pytest_cache",
    ".ruff_cache",
})

_SKIP_EXT: frozenset[str] = frozenset({
    ".pyc", ".pyo", ".pyd",
    ".so", ".dll", ".dylib",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp",
    ".woff", ".woff2", ".ttf", ".eot",
    ".mp4", ".avi", ".mov",
    ".zip", ".tar", ".gz", ".whl",
    ".lock",
})

_MAX_DIFF_SIZE_CHARS: int = 50000


def _should_skip(rel_path_str: str) -> bool:
    parts = rel_path_str.replace("\\", "/").split("/")
    if any(p in _SKIP_DIRS for p in parts):
        return True
    ext = Path(rel_path_str).suffix.lower()
    if ext in _SKIP_EXT:
        return True
    if "frontend/dist" in rel_path_str.replace("\\", "/"):
        return True
    if "frontend/node_modules" in rel_path_str.replace("\\", "/"):
        return True
    return False


def _is_text_file(path: Path) -> bool:
    try:
        path.read_bytes()
        path.read_text(encoding="utf-8")
        return True
    except (UnicodeDecodeError, ValueError, OSError):
        return False


# ---------------------------------------------------------------------------
# 文件收集
# ---------------------------------------------------------------------------

def _collect_files(root: Path) -> Dict[str, Path]:
    files: Dict[str, Path] = {}
    if not root.is_dir():
        return files
    for f in root.rglob("*"):
        if not f.is_file():
            continue
        rel = str(f.relative_to(root))
        if _should_skip(rel):
            continue
        if not _is_text_file(f):
            continue
        files[rel] = f
    return files


# ---------------------------------------------------------------------------
# 核心对比引擎
# ---------------------------------------------------------------------------

def _compare_dirs(
    left_root: Path,
    right_root: Path,
    left_label: str,
    right_label: str,
    path_filter: str,
    pattern: str,
    context_lines: int,
    max_files: int,
) -> str:
    """对比两个目录的文件并返回 unified diff 结果。

    参数
    ----
    left / right : 两个被比较的目录根路径
    left_label / right_label : diff 头中显示的名称（如 "origin_agent"）
    path_filter : 子串过滤，只对比路径包含此串的文件
    pattern : glob 模式过滤
    context_lines : diff 上下文行数
    max_files : 最多返回差异文件数
    """
    left_files: Dict[str, Path] = _collect_files(left_root)
    right_files: Dict[str, Path] = _collect_files(right_root)

    all_paths: List[str] = sorted(set(left_files) | set(right_files))
    if path_filter:
        all_paths = [p for p in all_paths if path_filter in p.replace("\\", "/")]
    if pattern:
        all_paths = [p for p in all_paths if fnmatch.fnmatch(p, pattern)]

    stats: Dict[str, int] = {
        "total_left": len(left_files),
        "total_right": len(right_files),
        "same": 0,
        "modified": 0,
        "missing_in_right": 0,
        "new_in_right": 0,
        "skipped_max": 0,
    }

    diffs: List[Dict[str, Any]] = []

    for rel_path in all_paths:
        if len(diffs) >= max_files:
            stats["skipped_max"] = len(all_paths) - all_paths.index(rel_path)
            break

        left_file: Path | None = left_files.get(rel_path)
        right_file: Path | None = right_files.get(rel_path)

        if left_file is not None and right_file is None:
            stats["missing_in_right"] += 1
            diffs.append({"file": rel_path, "status": "missing_in_right"})
            continue

        if left_file is None and right_file is not None:
            stats["new_in_right"] += 1
            diffs.append({"file": rel_path, "status": "new_in_right"})
            continue

        # Both exist
        try:
            left_text: str = left_file.read_text(encoding="utf-8")
            right_text: str = right_file.read_text(encoding="utf-8")
        except Exception:
            continue

        if left_text == right_text:
            stats["same"] += 1
            continue

        stats["modified"] += 1

        diff_lines: List[str] = list(difflib.unified_diff(
            left_text.splitlines(keepends=True),
            right_text.splitlines(keepends=True),
            fromfile=f"{left_label}/{rel_path}",
            tofile=f"{right_label}/{rel_path}",
            n=context_lines,
        ))
        diff_text: str = "".join(diff_lines)

        if len(diff_text) > _MAX_DIFF_SIZE_CHARS:
            diff_text = diff_text[:_MAX_DIFF_SIZE_CHARS]
            diff_text += f"\n\n... (truncated, {_MAX_DIFF_SIZE_CHARS} chars max)"

        diffs.append({
            "file": rel_path,
            "status": "modified",
            "diff": diff_text,
        })

    return tool_result(
        stats=stats,
        left_path=str(left_root),
        right_path=str(right_root),
        diffs=diffs,
    )


# ---------------------------------------------------------------------------
# Handler: diff_origin_fast
# ---------------------------------------------------------------------------

def _handle_diff_origin_fast(args: Dict[str, Any]) -> str:
    if not _ORIGIN_ROOT.is_dir():
        return tool_error(f"origin_agent not found: {_ORIGIN_ROOT}")
    if not _FAST_ROOT.is_dir():
        return tool_error(f"fast_agent not found: {_FAST_ROOT}")

    return _compare_dirs(
        left_root=_ORIGIN_ROOT,
        right_root=_FAST_ROOT,
        left_label="origin_agent",
        right_label="fast_agent",
        path_filter=str(args.get("path", "")).strip(),
        pattern=str(args.get("pattern", "")).strip(),
        context_lines=int(args.get("context_lines", 3)),
        max_files=int(args.get("max_files", 50)),
    )


# ---------------------------------------------------------------------------
# Handler: diff_fast_fork
# ---------------------------------------------------------------------------

_FORK_ROOT_CACHE: Path | None = None


def _get_fork_root() -> Path | None:
    global _FORK_ROOT_CACHE
    if _FORK_ROOT_CACHE is None:
        _FORK_ROOT_CACHE = _resolve_fork_root()
    return _FORK_ROOT_CACHE


def _handle_diff_fast_fork(args: Dict[str, Any]) -> str:
    if not _FAST_ROOT.is_dir():
        return tool_error(f"fast_agent not found: {_FAST_ROOT}")

    fork_root: Path | None = _get_fork_root()
    if fork_root is None:
        return tool_error(
            "fork (slow) directory not found. "
            "The sandbox or slow_agent_space is not available in this mode.",
        )

    if not fork_root.is_dir():
        return tool_error(f"fork directory not found: {fork_root}")

    return _compare_dirs(
        left_root=_FAST_ROOT,
        right_root=fork_root,
        left_label="fast_agent",
        right_label="fork",
        path_filter=str(args.get("path", "")).strip(),
        pattern=str(args.get("pattern", "")).strip(),
        context_lines=int(args.get("context_lines", 3)),
        max_files=int(args.get("max_files", 50)),
    )


# ---------------------------------------------------------------------------
# 通用 schema 定义
# ---------------------------------------------------------------------------

_COMMON_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": (
                "可选路径过滤子串。只对比路径中包含此字符串的文件。"
                "例如传入 'tools/' 只对比 tools 目录下的文件。"
            ),
        },
        "pattern": {
            "type": "string",
            "description": (
                "可选 glob 模式过滤。例如 '*.py' 只比较 Python 文件，"
                "'**/filesystem.py' 匹配所有 filesystem.py。"
            ),
        },
        "context_lines": {
            "type": "integer",
            "description": "unified diff 上下文行数（默认 3）。",
            "default": 3,
        },
        "max_files": {
            "type": "integer",
            "description": "最多返回多少个有差异的文件结果（默认 50）。",
            "default": 50,
        },
    },
}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

registry.register(
    name="diff_origin_fast",
    toolset="extools",
    schema={
        "description": (
            "对比原始源码仓库（origin_agent/）与当前正在运行的 "
            "fast 仓库（fast_agent_space/）之间的代码差异。"
            "origin_agent 是代码真相来源，fast 是运行时副本。"
            "每次代码进化（slow→fast 交换）可能导致二者产生差异，"
            "进化次数越多差异越大。此工具用于审查当前运行版本"
            "相对于最初源代码的偏离程度。"
        ),
        **_COMMON_SCHEMA,
    },
    handler=_handle_diff_origin_fast,
    emoji="🔍",
)

registry.register(
    name="diff_fast_fork",
    toolset="extools",
    schema={
        "description": (
            "对比当前运行的 fast 仓库（fast_agent_space/）与 "
            "fork 目录（slow_agent_space/ 进化目标）之间的代码差异。"
            "写进化代码到 fork 后，可通过此工具审查即将被交换的变更。"
            "如果二者一致则无需调用 evolve_code。"
        ),
        **_COMMON_SCHEMA,
    },
    handler=_handle_diff_fast_fork,
    emoji="🔁",
)