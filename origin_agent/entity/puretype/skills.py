from typing import Any

# ---------------------------------------------------------------------------
# Skills Types
# ---------------------------------------------------------------------------

SkillPayload = dict[str, Any]
"""Serializable dict representing a loaded skill.

Keys:
    success: bool
    name: str
    path: str (relative path within the skills directory)
    skill_dir: str (absolute path to the skill directory)
    content: str (rendered markdown body)
    raw_content: str (unrendered markdown body)
    frontmatter: dict
    description: str
    category: str | None
    tags: list[str]
    linked_files: dict[str, list[str]]
    setup_needed: bool
    setup_note: str | None
    readiness_status: str
    error: str | None (on failure)
"""

SkillInfo = dict[str, Any]
"""Minimal skill metadata for listing.

Keys:
    name: str
    description: str
    category: str | None
    tags: list[str]
    path: str
    skill_dir: str
"""