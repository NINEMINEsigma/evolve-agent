"""Hermes Skills — standalone skill loading, discovery, and management.

No external dependencies. Pure Python stdlib.
"""

from .frontmatter import parse_frontmatter, load_frontmatter_only
from .loader import load_skill, list_skills, SkillPayload, SkillInfo
from .manager import create_skill, update_skill, delete_skill, write_skill_file, read_skill_file
