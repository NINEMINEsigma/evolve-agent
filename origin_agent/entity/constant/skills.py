"""Skill 扫描和内联 Shell 模板常量。"""

import re


# ============================================================================
# Skill
# ============================================================================

# Skill 文件关联扫描排除的目录/文件模式（黑名单）
IGNORED_DIRS: frozenset[str] = frozenset({
    "__pycache__", ".git", ".github", ".hub", ".archive",
    "node_modules", ".venv", "__pypackages__",
})

# 默认 skills 目录名称
DEFAULT_SKILLS_DIR: str = "skills"

# Inline shell 模板模式: {{ command }}
_INLINE_SHELL_RE = re.compile(r"\u007b\u007b\s*(.+?)\s*\u007d\u007d")
