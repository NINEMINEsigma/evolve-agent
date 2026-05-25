"""Prompt template loader.

Reads layered ``.txt`` templates from ``templates/`` relative to the
agent's root directory.  Templates are combined at runtime based on the
agent's mode (fast / fallback) and available subsystems (tools, memory).

Directory layout::

    templates/
      base.txt          — always included
      modes/
        fast.txt        — fast mode additions
        fallback.txt    — fallback mode additions
      tools.txt         — tool usage instructions (Stage 4+)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Resolve the templates directory relative to this file.
# This works both in the source tree (origin_agent/system/)
# and in the workspace copy (workspace/fast_agent_space/system/).
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

from system.pathutils import find_repo_root


def _read_gene() -> str:
    """Read the immutable GENE.md from the project root."""
    return _read_if_exists(find_repo_root() / "GENE.md")


def _read_soul(workspace: Path) -> str:
    """Read the editable SOUL.md from the workspace directory."""
    return _read_if_exists(workspace / "SOUL.md")


def _platform_info(lang: str = "en") -> str:
    """Detect the runtime platform and return a prompt block describing it.

    Returns a short paragraph telling the LLM which OS it runs on, what
    the correct Python binary is called, and how to invoke shell commands.
    """
    is_win = sys.platform.startswith("win")
    is_mac = sys.platform == "darwin"

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
    """Return file contents as a stripped string, or '' if missing."""
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
    self_path: str = "",
    fork_path: str = "",
    fix_fork_path: str = "",
    fix_log_path: str = "",
) -> str:
    """Assemble the full system prompt from layered templates.

    Parameters
    ----------
    mode:
        ``"fast"`` or ``"fallback"`` — selects the mode-specific template.
    memory_context:
        Memory prefetch text to append after the prompt.
    extra_blocks:
        Additional sections appended after the mode section (e.g. skill
        prompts, memory provider blocks).
    lang:
        ``"en"`` (default) or ``"zh"`` — selects template language variant.
    workspace:
        Path to the workspace directory for reading SOUL.md.
    self_path / fork_path / fix_fork_path / fix_log_path:
        Real paths for ``{self_path}`` / ``{fork_path}`` / ``{fix_fork_path}`` / ``{fix_log_path}``
        placeholders in template files (converted from ``{{var}}`` by .format(), then
        replaced via .replace()).

    Returns
    -------
    str
        The assembled system prompt ready for the LLM.
    """
    template_root = _TEMPLATES_DIR
    if lang == "zh":
        zh_dir = _TEMPLATES_DIR / "zh"
        if zh_dir.is_dir():
            template_root = zh_dir

    blocks: list[str] = []

    # 0. GENE — immutable core identity, always first
    gene = _read_gene()
    if gene:
        blocks.append(gene)

    # 0a. SOUL — human+AI co-editable personality/style (workspace/SOUL.soul)
    workspace_path = Path(workspace) if workspace else Path()
    soul = _read_soul(workspace_path)
    if soul:
        blocks.append(soul)

    # 1. Base
    base = _read_if_exists(template_root / "base.txt")
    if base:
        base = base.format(platform=_platform_info(lang))
        base = base.replace("{self_path}", self_path)
        base = base.replace("{fork_path}", fork_path)
        blocks.append(base)

    # 2. Mode-specific
    mode_block = _read_if_exists(template_root / "modes" / f"{mode}.txt")
    if mode_block:
        mode_block = mode_block.replace("{fix_fork_path}", fix_fork_path)
        mode_block = mode_block.replace("{fix_log_path}", fix_log_path)
        blocks.append(mode_block)

    # 3. Tools
    tools = _read_if_exists(template_root / "tools.txt")
    if tools:
        blocks.append(tools)

    # 4. Memory context
    if memory_context:
        blocks.append(memory_context)

    # 5. Extra blocks (skills, memory provider, etc.)
    if extra_blocks:
        for block in extra_blocks:
            if block and block.strip():
                blocks.append(block.strip())

    return "\n\n".join(blocks)