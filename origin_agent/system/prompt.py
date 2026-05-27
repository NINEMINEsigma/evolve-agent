"""Prompt 模板加载器。

从 agent 根目录下的 ``templates/`` 读取分层 ``.txt`` 模板。
模板在运行时根据 agent 模式（fast / fallback）和可用子系统
（tools、memory）组合。

目录布局::

    templates/
      base.txt          — 始终包含
      modes/
        fast.txt        — fast 模式附加
        fallback.txt    — fallback 模式附加
      tools.txt         — 工具使用说明（Stage 4+）
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 解析相对于此文件的 templates 目录。
# 在源码树（origin_agent/system/）和 workspace 副本
# （workspace/fast_agent_space/system/）中均可工作。
_TEMPLATES_DIR: Path = Path(__file__).resolve().parent.parent / "templates"

from system.pathutils import find_repo_root


def _read_gene() -> str:
    """从项目根目录读取不可变的 GENE.md。"""
    return _read_if_exists(find_repo_root() / "GENE.md")


def _read_soul(workspace: Path) -> str:
    """从 workspace 目录读取可编辑的 SOUL.md。"""
    return _read_if_exists(workspace / "SOUL.md")


def _platform_info(lang: str = "en") -> str:
    """检测运行时平台并返回描述该平台的 prompt 块。

    返回一个简短段落，告知 LLM 运行在哪个操作系统上、
    正确的 Python 二进制名称以及如何调用 shell 命令。
    """
    is_win: bool = sys.platform.startswith("win")
    is_mac: bool = sys.platform == "darwin"

    if lang == "zh":
        if is_win:
            return (
                "运行平台：**Windows**。Python 命令是 ``python``（不是 ``python3``）。\n"
                "Windows 原生命令使用 ``cmd /c <命令>`` 形式。"
            )
        if is_mac:
            return (
                "运行平台：**macOS**。Python 命令是 ``python3``。\n"
                "使用标准 Unix shell 命令。"
            )
        return (
            "运行平台：**Linux**。Python 命令是 ``python3``。\n"
            "使用标准 Unix shell 命令。"
        )
    # English
    if is_win:
        return (
            "Running on **Windows**.  Python is ``python`` (not ``python3``).\n"
            "For Windows built-in commands use ``cmd /c <command>``."
        )
    if is_mac:
        return (
            "Running on **macOS**.  Python is ``python3``.\n"
            "Use standard Unix shell commands."
        )
    return (
        "Running on **Linux**.  Python is ``python3``.\n"
        "Use standard Unix shell commands."
    )


def _read_if_exists(path: Path) -> str:
    """返回文件内容的去空白字符串，缺失时返回 ''。"""
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning("Failed to read template %s: %s", path, exc)
        return ""


def build_system_prompt(
    mode: str = "fast",
    memory_context: str = "",
    extra_blocks: Optional[list[str]] = None,
    lang: str = "en",
    workspace: Path | str = "",
    agentspace: str = "",
    fork_path: str = "",
    fix_fork_path: str = "",
    fix_log_path: str = "",
) -> str:
    """从分层模板组装完整的 system prompt。

    参数
    ----------
    mode:
        ``"fast"`` 或 ``"fallback"`` — 选择模式特定的模板。
    memory_context:
        追加在 prompt 之后的 memory 预取文本。
    extra_blocks:
        追加在模式段之后的额外节（例如 skill prompt、memory provider 块）。
    lang:
        ``"en"``（默认）或 ``"zh"`` — 选择模板语言变体。
    workspace:
        workspace 目录路径，用于读取 SOUL.md。
    fork_path / fix_fork_path / fix_log_path:
        模板文件中 ``{fork_path}`` / ``{fix_fork_path}`` / ``{fix_log_path}``
        占位符的真实路径（通过 .format() 将 ``{{var}}`` 转换后再替换）。

    返回
    -------
    str
        组装完成的 system prompt，可直接用于 LLM。
    """
    template_root: Path = _TEMPLATES_DIR
    if lang == "zh":
        zh_dir: Path = _TEMPLATES_DIR / "zh"
        if zh_dir.is_dir():
            template_root = zh_dir

    blocks: list[str] = []

    # 0. GENE — 不可变的核心身份，始终在最前面
    gene: str = _read_gene()
    if gene:
        blocks.append(gene)

    # 0a. SOUL — 人+AI 共同编辑的个性/风格（workspace/SOUL.soul）
    workspace_path: Path = Path(workspace) if workspace else Path()
    soul: str = _read_soul(workspace_path)
    if soul:
        blocks.append(soul)

    # 1. 基础
    base: str = _read_if_exists(template_root / "base.txt")
    if base:
        base = base.replace(r"{{platform}}", _platform_info(lang))
        base = base.replace(r"{{agentspace}}", agentspace)
        base = base.replace(r"{{fork_path}}", fork_path)
        blocks.append(base)

    # 2. 模式特定
    mode_block: str = _read_if_exists(template_root / "modes" / f"{mode}.txt")
    if mode_block:
        mode_block = mode_block.replace(r"{{fix_fork_path}}", fix_fork_path)
        mode_block = mode_block.replace(r"{{fix_log_path}}", fix_log_path)
        blocks.append(mode_block)

    # 3. 工具
    tools: str = _read_if_exists(template_root / "tools.txt")
    if tools:
        blocks.append(tools)

    # 4. Memory 上下文
    if memory_context:
        blocks.append(memory_context)

    # 5. 额外块（skills、memory provider 等）
    if extra_blocks:
        for block in extra_blocks:
            if block and block.strip():
                blocks.append(block.strip())

    return "\n\n".join(blocks)