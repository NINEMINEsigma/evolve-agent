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
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Resolve the templates directory relative to this file.
# This works both in the source tree (origin_agent/system/)
# and in the workspace copy (workspace/fast_agent_space/system/).
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


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

    # 1. Base
    base = _read_if_exists(template_root / "base.txt")
    if base:
        blocks.append(base)

    # 2. Mode-specific
    mode_block = _read_if_exists(template_root / "modes" / f"{mode}.txt")
    if mode_block:
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