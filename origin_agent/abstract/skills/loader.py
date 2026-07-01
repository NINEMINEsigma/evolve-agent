"""Skill loader — load and render SKILL.md files from disk.

Provides the core ``load_skill()`` function that reads a skill by name/path,
parses its frontmatter, applies template substitution, and returns a
structured payload.

Zero external dependencies — pure Python stdlib + ``hermes_skills.frontmatter``.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess  # nosec: intentional for inline shell expansion
from pathlib import Path
from typing import Any, Dict, List, Optional

from entity.constant import DEFAULT_SKILLS_DIR, IGNORED_DIRS, _INLINE_SHELL_RE
from entity.puretype import SkillPayload, SkillInfo
from .frontmatter import parse_frontmatter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Skill loading
# ---------------------------------------------------------------------------


def load_skill(
    name_or_path: str,
    skills_dir: Optional[Path] = None,
    external_dirs: Optional[list[Path]] = None,
    task_id: str | None = None,
    preprocess: bool = True,
    inline_shell: bool = False,
    inline_shell_timeout: int = 10,
    template_vars: Optional[dict[str, str]] = None,
) -> SkillPayload:
    """Load a skill by name or path.

    Args:
        name_or_path: Skill name (e.g. ``"gif-search"``) or absolute path to a
            SKILL.md file.
        skills_dir: Base directory for skills. Defaults to
            ``./skills`` relative to CWD.
        external_dirs: Additional directories to search for skills.
        task_id: Optional task identifier (used for template vars).
        preprocess: Apply template variable substitution.
        inline_shell: Execute ``{{ shell command }}`` inline blocks.
        inline_shell_timeout: Timeout in seconds for inline shell commands.
        template_vars: Optional dict of template variables. If None, defaults
            are used (user=os.environ, session_id=task_id).

    Returns:
        A :data:`SkillPayload` dict.
    """
    skills_dir = skills_dir or Path.cwd() / DEFAULT_SKILLS_DIR
    external_dirs = external_dirs or []
    template_vars = template_vars or _default_template_vars(task_id)

    # Resolve the skill file path
    skill_path = _resolve_skill_path(name_or_path, skills_dir, external_dirs)
    if skill_path is None:
        return _error_payload(f"Skill not found: {name_or_path}")

    if not skill_path.exists():
        return _error_payload(f"Skill file not found: {skill_path}")

    skill_dir = skill_path.parent

    try:
        raw_content = skill_path.read_text(encoding="utf-8")
    except Exception as e:
        return _error_payload(f"Failed to read skill: {e}")

    frontmatter, body = parse_frontmatter(raw_content)
    name = str(frontmatter.get("name", skill_dir.name))
    description = str(frontmatter.get("description", ""))
    category = frontmatter.get("category") or _infer_category(
        skill_dir, skills_dir
    )
    tags = frontmatter.get("tags", []) or []
    if isinstance(tags, str):
        tags = [tags]

    # Build relative path
    try:
        rel_path = str(skill_path.relative_to(skills_dir))
    except ValueError:
        rel_path = str(skill_path)

    # Process content
    content = body
    if preprocess and template_vars:
        content = _substitute_template_vars(content, skill_dir, template_vars)
    if inline_shell:
        content = _expand_inline_shell(content, skill_dir, inline_shell_timeout)

    # Discover linked files
    linked_files = _discover_linked_files(skill_dir)

    # Setup status
    setup_metadata = _check_setup_status(frontmatter, skill_dir)

    return {
        "success": True,
        "name": name,
        "path": rel_path,
        "skill_dir": str(skill_dir.resolve()),
        "content": content,
        "raw_content": body,
        "frontmatter": frontmatter,
        "description": description,
        "category": category,
        "tags": tags if isinstance(tags, list) else [tags],
        "linked_files": linked_files,
        **setup_metadata,
        "error": None,
    }


def list_skills(
    skills_dir: Optional[Path] = None,
    external_dirs: Optional[list[Path]] = None,
    category: str | None = None,
    disabled: Optional[list[str]] = None,
) -> list[SkillInfo]:
    """List all available skills with minimal metadata.

    Args:
        skills_dir: Base skills directory.
        external_dirs: Additional skill directories.
        category: Optional category filter.
        disabled: List of disabled skill names to skip.

    Returns:
        List of :data:`SkillInfo` dicts.
    """
    skills_dir = skills_dir or Path.cwd() / DEFAULT_SKILLS_DIR
    external_dirs = external_dirs or []
    disabled = disabled or []
    seen: set = set()
    results: list[SkillInfo] = []

    for scan_dir in [skills_dir] + external_dirs:
        if not scan_dir.exists():
            continue
        for skill_md in _iter_skill_index_files(scan_dir, "SKILL.md"):
            # Skip hidden dirs and git artifacts
            parts = skill_md.parts
            if any(part in {".git", ".github", ".hub", ".archive"} for part in parts):
                continue

            try:
                content = skill_md.read_text(encoding="utf-8")
                frontmatter, body_text = parse_frontmatter(content)
            except Exception:
                logger.warning("Failed to parse skill frontmatter: %s", skill_md, exc_info=True)
                continue

            name = str(frontmatter.get("name", skill_md.parent.name))
            if name in seen:
                continue
            seen.add(name)

            if name in disabled:
                continue

            if category:
                skill_cat = frontmatter.get("category") or _infer_category(
                    skill_md.parent, skills_dir
                )
                if skill_cat != category:
                    continue

            description = str(
                frontmatter.get("description")
                or _first_non_heading_line(body_text)
                or ""
            )

            tags = frontmatter.get("tags", []) or []
            if isinstance(tags, str):
                tags = [tags]

            try:
                rel_path = str(skill_md.relative_to(skills_dir))
            except ValueError:
                rel_path = str(skill_md)

            results.append({
                "name": name,
                "description": description,
                "category": frontmatter.get("category")
                or _infer_category(skill_md.parent, skills_dir),
                "tags": tags,
                "path": rel_path,
                "skill_dir": str(skill_md.parent.resolve()),
            })

    # Sort by category, then name
    results.sort(key=lambda s: (s.get("category") or "", s["name"]))
    return results


# ---------------------------------------------------------------------------
# Skill file resolution
# ---------------------------------------------------------------------------


def _resolve_skill_path(
    name_or_path: str, skills_dir: Path, external_dirs: list[Path]
) -> Path|None:
    """Resolve a skill name or path to a SKILL.md file."""
    p = Path(name_or_path).expanduser()

    # If it's an absolute path, check trusted roots
    if p.is_absolute():
        trusted_roots = [skills_dir] + external_dirs
        for root in trusted_roots:
            try:
                p.relative_to(root)
                if p.name == "SKILL.md":
                    return p
                return p / "SKILL.md"
            except ValueError:
                continue
        # Not under any trusted root — try resolving
        resolved = p.resolve()
        if resolved.suffix == ".md":
            return resolved
        return resolved / "SKILL.md"

    # Relative name — search in skills dirs (direct and one-level nested)
    candidate = skills_dir / name_or_path / "SKILL.md"
    if candidate.exists():
        return candidate

    # Search in category subdirectories (category/name/SKILL.md)
    for child in skills_dir.iterdir():
        if child.is_dir() and not child.name.startswith("."):
            candidate = child / name_or_path / "SKILL.md"
            if candidate.exists():
                return candidate

    for ext_dir in external_dirs:
        candidate = ext_dir / name_or_path / "SKILL.md"
        if candidate.exists():
            return candidate

    return None


def _iter_skill_index_files(base_dir: Path, index_name: str) -> list[Path]:
    """Find all *index_name* files under *base_dir*, breadth-first limited."""
    results: list[Path] = []
    if not base_dir.exists():
        return results

    # Direct children first (categorized skills: category/skill/SKILL.md)
    for child in sorted(base_dir.iterdir()):
        if child.is_dir() and not child.name.startswith("."):
            skill_md = child / index_name
            if skill_md.exists():
                results.append(skill_md)

    # Also check nested (flat structure)
    for skill_md in sorted(base_dir.rglob(index_name)):
        if skill_md not in results and skill_md.parent != base_dir:
            if len(skill_md.relative_to(base_dir).parts) <= 3:
                results.append(skill_md)

    return results


# ---------------------------------------------------------------------------
# Template substitution
# ---------------------------------------------------------------------------


def _default_template_vars(task_id: str | None = None) -> dict[str, str]:
    """Return default template variables."""
    return {
        "user": os.environ.get("USER", "unknown"),
        "home": str(Path.home()),
        "cwd": str(Path.cwd()),
        "session_id": task_id or "",
    }


def _substitute_template_vars(
    content: str, skill_dir: Optional[Path], vars: dict[str, str]
) -> str:
    """Replace ``{{ var_name }}`` placeholders with values from *vars*.

    Supports:
      - ``{{ var_name }}`` — simple variable
      - ``{{ var_name | default("fallback") }}`` — with default
    """
    def _replacer(m: re.Match) -> str:
        expr = m.group(1).strip()
        if "|" in expr:
            parts = [p.strip() for p in expr.split("|", 1)]
            var_name = parts[0]
            if var_name in vars:
                return str(vars[var_name])
            default_match = re.search(r'default\(["\'](.+?)["\']\)', parts[1])
            if default_match:
                return default_match.group(1)
            return ""
        return str(vars.get(expr, ""))

    return re.sub(r"\u007b\u007b\s*(.+?)\s*\u007d\u007d", _replacer, content)


def _expand_inline_shell(
    content: str, skill_dir: Optional[Path], timeout: int = 10
) -> str:
    """Execute ``{{ shell command }}`` blocks and replace with output.

    WARNING: This executes arbitrary shell commands. Only enable when
    the skill content is from a trusted source.
    """
    cwd = str(skill_dir) if skill_dir else None

    def _run(m: re.Match) -> str:
        cmd = m.group(1).strip()
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
            output = (result.stdout or "").strip()
            return output if output else f"<!-- shell command failed: {cmd} -->"
        except subprocess.TimeoutExpired:
            return f"<!-- shell command timed out: {cmd} -->"
        except Exception as e:
            return f"<!-- shell command error: {e} -->"

    return _INLINE_SHELL_RE.sub(_run, content)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _discover_linked_files(skill_dir: Path) -> dict[str, list[str]]:
    """Scan the entire skill directory for supporting files (blacklist-based).

    Excludes directories and patterns listed in ``IGNORED_DIRS`` as well
    as any hidden entry (starting with ``.``).
    """
    linked: dict[str, list[str]] = {}
    if not skill_dir.exists():
        return linked

    for f in sorted(skill_dir.rglob("*")):
        if not f.is_file() or f.is_symlink():
            continue

        rel = f.relative_to(skill_dir)
        parts = rel.parts

        # Skip hidden entries (dotfiles / dotdirs)
        if any(p.startswith(".") for p in parts):
            continue

        # Skip blacklisted directories
        if any(p in IGNORED_DIRS for p in parts):
            continue

        # Group by top-level subdir (or "" for files at root)
        parent = str(parts[0]) if len(parts) > 1 else ""
        linked.setdefault(parent, []).append(str(rel))

    return linked


def _check_setup_status(
    frontmatter: dict[str, Any], skill_dir: Path
) -> dict[str, Any]:
    """Check if a skill requires setup."""
    required_env = frontmatter.get("required_environment_variables", []) or []
    if isinstance(required_env, str):
        required_env = [required_env]

    missing_env = [v for v in required_env if not os.environ.get(v)]

    required_commands = frontmatter.get("required_commands", []) or []
    if isinstance(required_commands, str):
        required_commands = [required_commands]

    missing_commands = []
    for cmd in required_commands:
        if not _command_exists(cmd):
            missing_commands.append(cmd)

    setup_needed = bool(missing_env or missing_commands)
    setup_notes = []
    if missing_env:
        setup_notes.append(f"Missing env vars: {', '.join(missing_env)}")
    if missing_commands:
        setup_notes.append(f"Missing commands: {', '.join(missing_commands)}")

    return {
        "setup_needed": setup_needed,
        "setup_note": "; ".join(setup_notes) if setup_notes else None,
        "readiness_status": "needs_setup" if setup_needed else "available",
    }


def _command_exists(cmd: str) -> bool:
    """Check if a shell command is available on PATH."""
    return any(
        (Path(p) / cmd).exists() or (Path(p) / f"{cmd}.exe").exists()
        for p in os.environ.get("PATH", "").split(os.pathsep)
    )


def _infer_category(skill_dir: Path, skills_base: Path) -> str | None:
    """Infer skill category from its parent directory structure."""
    try:
        rel = skill_dir.relative_to(skills_base)
        parts = rel.parts
        if len(parts) >= 2:
            return parts[0]
    except ValueError:
        pass
    return None


def _first_non_heading_line(body: str) -> str | None:
    """Return the first non-empty, non-heading line of *body*."""
    for line in body.strip().split("\n"):
        line = line.strip()
        if line and not line.startswith("#"):
            return line[:80]
    return None


def _error_payload(message: str) -> SkillPayload:
    """Return an error skill payload."""
    return {
        "success": False,
        "name": "",
        "path": "",
        "skill_dir": "",
        "content": "",
        "raw_content": "",
        "frontmatter": {},
        "description": "",
        "category": None,
        "tags": [],
        "linked_files": {},
        "setup_needed": False,
        "setup_note": None,
        "readiness_status": "error",
        "error": message,
    }
