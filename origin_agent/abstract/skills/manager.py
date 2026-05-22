"""Skill manager — create, update, and delete SKILL.md files.

Provides high-level operations for managing skills on disk, including
skill directory creation, frontmatter scaffolding, and safe deletion.

Zero external dependencies — pure Python stdlib + ``hermes_skills`` internals.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .frontmatter import parse_frontmatter
from .loader import (
    DEFAULT_SKILLS_DIR,
    SkillPayload,
    _iter_skill_index_files,
    _resolve_skill_path,
    load_skill,
)


def create_skill(
    name: str,
    skills_dir: Optional[Path] = None,
    description: str = "",
    category: Optional[str] = None,
    content: str = "",
    author: str = "Hermes Agent",
    version: str = "1.0.0",
    tags: Optional[List[str]] = None,
    **extra_frontmatter: Any,
) -> SkillPayload:
    """Create a new skill on disk.

    Args:
        name: Skill name (used as directory name and in frontmatter).
        skills_dir: Base skills directory.
        description: Short description of the skill.
        category: Category/directory grouping (e.g. ``"mlops"``).
        content: Markdown body content.
        author: Author name for frontmatter.
        version: Version string.
        tags: List of tags.
        **extra_frontmatter: Additional YAML frontmatter fields.

    Returns:
        The loaded skill payload for the newly created skill.
    """
    skills_dir = skills_dir or Path.cwd() / DEFAULT_SKILLS_DIR
    tags = tags or []

    # Determine the skill directory path
    if category:
        skill_dir = skills_dir / category / name
    else:
        skill_dir = skills_dir / name

    skill_md = skill_dir / "SKILL.md"

    if skill_md.exists():
        return {
            "success": False,
            "error": f"Skill '{name}' already exists at {skill_md}",
            "name": name,
            "path": str(skill_md),
            "skill_dir": str(skill_dir),
            "content": "",
            "raw_content": "",
            "frontmatter": {},
            "description": "",
            "category": category,
            "tags": [],
            "linked_files": {},
            "setup_needed": False,
            "setup_note": None,
            "readiness_status": "error",
        }

    # Create directories
    skill_dir.mkdir(parents=True, exist_ok=True)

    # Build frontmatter
    frontmatter_lines = ["---"]
    frontmatter_lines.append(f"name: {name}")
    frontmatter_lines.append(f"description: \"{description}\"")
    frontmatter_lines.append(f"version: {version}")
    frontmatter_lines.append(f"author: {author}")
    if category:
        frontmatter_lines.append(f"category: {category}")
    if tags:
        tags_yaml = "\n" + "\n".join(f"  - {t}" for t in tags)
        frontmatter_lines.append(f"tags:{tags_yaml}")
    for key, value in extra_frontmatter.items():
        if isinstance(value, str):
            frontmatter_lines.append(f"{key}: \"{value}\"")
        elif isinstance(value, bool):
            frontmatter_lines.append(f"{key}: {'true' if value else 'false'}")
        else:
            frontmatter_lines.append(f"{key}: {value}")
    frontmatter_lines.append("---")

    full_content = "\n".join(frontmatter_lines) + "\n\n" + content

    # Create supporting directories
    for subdir in ("references", "templates", "scripts", "assets"):
        (skill_dir / subdir).mkdir(exist_ok=True)
        (skill_dir / subdir / ".gitkeep").touch()

    skill_md.write_text(full_content, encoding="utf-8")

    return load_skill(str(skill_md), skills_dir)


def update_skill(
    name_or_path: str,
    skills_dir: Optional[Path] = None,
    description: Optional[str] = None,
    content: Optional[str] = None,
    tags: Optional[List[str]] = None,
    **frontmatter_updates: Any,
) -> SkillPayload:
    """Update an existing skill's frontmatter and/or body.

    Args:
        name_or_path: Skill name or path to SKILL.md.
        skills_dir: Base skills directory.
        description: New description (None = keep existing).
        content: New body content (None = keep existing).
        tags: New tags list (None = keep existing).
        **frontmatter_updates: Frontmatter fields to update.

    Returns:
        The updated skill payload.
    """
    skills_dir = skills_dir or Path.cwd() / DEFAULT_SKILLS_DIR

    payload = load_skill(name_or_path, skills_dir)
    if not payload.get("success"):
        return payload

    skill_dir = Path(payload["skill_dir"])
    skill_md = skill_dir / "SKILL.md"

    raw = skill_md.read_text(encoding="utf-8")
    current_fm, current_body = parse_frontmatter(raw)

    # Update frontmatter
    if description is not None:
        current_fm["description"] = description
    if tags is not None:
        current_fm["tags"] = tags
    current_fm.update(frontmatter_updates)

    # Apply body update if provided
    new_body = content if content is not None else current_body

    # Rebuild the file
    fm_block = _frontmatter_to_yaml(current_fm)
    new_raw = f"---\n{fm_block}---\n\n{new_body}"
    skill_md.write_text(new_raw, encoding="utf-8")

    return load_skill(str(skill_md), skills_dir)


def delete_skill(
    name_or_path: str,
    skills_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Delete a skill and its directory.

    Args:
        name_or_path: Skill name or path.
        skills_dir: Base skills directory.

    Returns:
        Dict with success status and message.
    """
    skills_dir = skills_dir or Path.cwd() / DEFAULT_SKILLS_DIR

    payload = load_skill(name_or_path, skills_dir)
    if not payload.get("success"):
        return {"success": False, "error": payload.get("error", "Skill not found")}

    skill_dir = Path(payload["skill_dir"])
    if not skill_dir.exists():
        return {"success": False, "error": f"Skill directory not found: {skill_dir}"}

    shutil.rmtree(skill_dir)

    return {
        "success": True,
        "message": f"Deleted skill '{payload.get('name', '')}'",
        "path": str(skill_dir),
    }


def _frontmatter_to_yaml(fm: Dict[str, Any]) -> str:
    """Serialize a frontmatter dict to YAML string (without delimiters).

    Uses a simple serializer that handles strings, bools, ints, lists,
    and nested dicts.
    """
    lines: List[str] = []
    for key, value in fm.items():
        if value is None:
            continue
        if isinstance(value, dict):
            lines.append(f"{key}:")
            for k, v in value.items():
                if isinstance(v, dict):
                    lines.append(f"  {k}:")
                    for k2, v2 in v.items():
                        lines.append(f"    {k2}: {_yaml_scalar(v2)}")
                else:
                    lines.append(f"  {k}: {_yaml_scalar(v)}")
        elif isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                if isinstance(item, dict):
                    lines.append(f"  -")
                    for k, v in item.items():
                        lines.append(f"    {k}: {_yaml_scalar(v)}")
                else:
                    lines.append(f"  - {_yaml_scalar(item)}")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    return "\n".join(lines) + ("\n" if lines else "")


def _yaml_scalar(value: Any) -> str:
    """Format a scalar value for YAML output."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    s = str(value)
    if any(c in s for c in (":", "#", "{", "}", "[", "]", ",", "&", "*", "?", "|", "-", "<", ">", "=", "!", "%", "@", "`", '"', "'")):
        if '"' in s:
            return f"'{s}'"
        return f'"{s}"'
    if s == "" or s[0] in (" ", "\t"):
        return f'"{s}"'
    return s
