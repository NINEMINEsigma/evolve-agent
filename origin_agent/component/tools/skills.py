"""Skill management tools — let the agent learn, list, and forget skills.

Registered at module-import time via ``registry.register()``.
Skills are managed through ``abstract.skills.manager`` which operates
on the ``workspace/skills/`` directory.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from abstract.skills.manager import create_skill, delete_skill, update_skill
from abstract.skills.loader import list_skills, load_skill
from abstract.tools.registry import registry, tool_error, tool_result
from system.sandbox import SandboxError

logger = logging.getLogger(__name__)

from .filesystem import _s as _get_sandbox


def _s():
    return _get_sandbox()


# ── helpers ──────────────────────────────────────────────────────────


def _skills_dir() -> str:
    """Resolve the skills directory path via the workspace sandbox."""
    try:
        return str(_s().resolve_read("ws:skills").real)
    except SandboxError:
        return "workspace/skills"


def _format_skill_list() -> str:
    """Return a formatted list of all registered skills."""
    try:
        skills = list_skills()
    except Exception:
        return json.dumps(
            {"error": "Failed to list skills", "skills": []},
            ensure_ascii=False,
        )
    result = []
    for s in skills:
        result.append({
            "name": s.get("name", ""),
            "description": s.get("description", ""),
            "category": s.get("category"),
            "tags": s.get("tags", []),
        })
    return json.dumps({"skills": result, "total": len(result)}, ensure_ascii=False)


# ── tool handlers ────────────────────────────────────────────────────


def _handle_learn_skill(args: Dict[str, Any]) -> str:
    """Create or update a skill with the given name and content."""
    name = str(args.get("name", "")).strip()
    content = str(args.get("content", "")).strip()
    description = str(args.get("description", "")).strip()
    category = str(args.get("category", "")).strip() or None
    tags = args.get("tags", []) or []

    if not name:
        return tool_error("name is required")
    if not content:
        return tool_error("content is required")

    try:
        payload = create_skill(
            name=name,
            description=description or name,
            category=category,
            content=content,
            tags=tags if isinstance(tags, list) else [str(tags)],
        )
        if not payload.get("success"):
            payload = update_skill(
                name=name,
                description=description or name,
                category=category,
                content=content,
                tags=tags if isinstance(tags, list) else [str(tags)],
            )
        if payload.get("success"):
            return tool_result(
                created=True,
                name=payload.get("name"),
                path=payload.get("path"),
            )
        return tool_error(payload.get("error", "Unknown error creating skill"))
    except Exception as exc:
        return tool_error(str(exc))


def _handle_list_skills(args: Dict[str, Any]) -> str:
    """List all available skills."""
    return _format_skill_list()


def _handle_forget_skill(args: Dict[str, Any]) -> str:
    """Delete a skill by name."""
    name = str(args.get("name", "")).strip()
    if not name:
        return tool_error("name is required")

    try:
        result = delete_skill(name)
        if result.get("success"):
            return tool_result(deleted=True, name=name)
        return tool_error(result.get("error", "Unknown error deleting skill"))
    except Exception as exc:
        return tool_error(str(exc))


def _handle_recall_skill(args: Dict[str, Any]) -> str:
    """Load a skill's full content into the conversation."""
    name = str(args.get("name", "")).strip()
    if not name:
        return _format_skill_list()

    try:
        payload = load_skill(name)
        if payload.get("success"):
            return json.dumps(
                {
                    "name": payload.get("name"),
                    "description": payload.get("description"),
                    "category": payload.get("category"),
                    "content": payload.get("content"),
                    "facts": payload.get("facts", []),
                },
                ensure_ascii=False,
            )
        return tool_error(payload.get("error", "Skill not found"))
    except Exception as exc:
        return tool_error(str(exc))


# ── registration ─────────────────────────────────────────────────────


registry.register(
    name="learn_skill",
    toolset="skills",
    schema={
        "description": (
            "Create or update a skill.  Skills are reusable knowledge "
            "modules stored as SKILL.md files in the workspace/skills/ "
            "directory.  Use this to persist useful knowledge that should "
            "carry across sessions.  If a skill with the same name already "
            "exists, it will be updated."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill name (short, kebab-case).",
                },
                "description": {
                    "type": "string",
                    "description": "One-line description of what the skill does.",
                },
                "content": {
                    "type": "string",
                    "description": "Markdown body of the skill.",
                },
                "category": {
                    "type": "string",
                    "description": "Optional category (e.g. 'utility', 'knowledge').",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags for filtering.",
                },
            },
            "required": ["name", "content"],
        },
    },
    handler=_handle_learn_skill,
    emoji="🧠",
)


registry.register(
    name="list_skills",
    toolset="skills",
    schema={
        "description": (
            "List all available skills with their names and descriptions."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    handler=_handle_list_skills,
    emoji="📋",
)


registry.register(
    name="forget_skill",
    toolset="skills",
    schema={
        "description": (
            "Delete a skill by name.  Use this to remove skills that are "
            "no longer relevant or useful."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the skill to delete.",
                },
            },
            "required": ["name"],
        },
    },
    handler=_handle_forget_skill,
    emoji="🗑️",
)


registry.register(
    name="recall_skill",
    toolset="skills",
    schema={
        "description": (
            "Load the full content of a skill into the conversation.  "
            "Use this to refresh your memory on a skill's details.  "
            "Call without arguments to list available skills."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill name to recall (omit to list all).",
                },
            },
        },
    },
    handler=_handle_recall_skill,
    emoji="🔍",
)