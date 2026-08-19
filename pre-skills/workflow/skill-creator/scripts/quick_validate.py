#!/usr/bin/env python3
"""
Quick validation script for skills — Evolve Agent 本地化版本。

纯 stdlib 实现（无 PyYAML 依赖），并适配 Evolve Agent 的 frontmatter 扩展字段：
name / description / license / allowed-tools / metadata / compatibility / version / author / category / tags
"""
import re
import sys
from pathlib import Path

# Evolve Agent 系统允许的 frontmatter 顶层字段
ALLOWED_PROPERTIES = {
    'name', 'description', 'license', 'allowed-tools', 'metadata',
    'compatibility', 'version', 'author', 'category', 'tags',
}

# 需要存在的字段
REQUIRED_PROPERTIES = {'name', 'description'}


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """极简 frontmatter 解析器（无 yaml 依赖）。

    返回 (frontmatter_dict, error_msg)。支持：
    - key: value  基本标量
    - 带引号的值（'...' / "..."）
    - 列表项（- item 归入前一个 key，或以逗号分隔的 [a, b, c]）
    只关心顶层键是否合法，不追求完整 YAML 语义。
    """
    if not content.startswith('---'):
        return {}, "No YAML frontmatter found"

    lines = content.split('\n')
    end_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == '---':
            end_idx = i
            break
    if end_idx is None:
        return {}, "Invalid frontmatter format (no closing ---)"

    frontmatter: dict = {}
    current_key = None
    for line in lines[1:end_idx]:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        # 列表项：- item 或 - item, ...
        if stripped.startswith('- ') and current_key is not None:
            item = stripped[2:].strip()
            if isinstance(frontmatter.get(current_key), list):
                frontmatter[current_key].append(item)
            else:
                frontmatter[current_key] = [item]
            continue
        # 行内列表：[a, b, c]
        m = re.match(r'^([A-Za-z0-9_-]+):\s*\[(.*)\]\s*$', stripped)
        if m:
            key = m.group(1).strip()
            items = [x.strip().strip('"').strip("'") for x in m.group(2).split(',') if x.strip()]
            frontmatter[key] = items
            current_key = key
            continue
        # 普通 key: value
        m = re.match(r'^([A-Za-z0-9_-]+):\s*(.*)$', stripped)
        if m:
            key = m.group(1).strip()
            value = m.group(2).strip()
            # 处理多行块指示符（> | >- |-）：值可能延续到后续行
            if value in ('>', '|', '>-', '|-', '>+', '|+'):
                continuation: list[str] = []
                # 在剩余行中收集缩进行
                rest_idx = lines[1:end_idx].index(line) + 1
                for cont_line in lines[1 + rest_idx:end_idx]:
                    if cont_line.startswith(('  ', '\t')):
                        continuation.append(cont_line.strip())
                    else:
                        break
                value = ' '.join(continuation) if continuation else ''
            value = value.strip('"').strip("'")
            frontmatter[key] = value
            current_key = key
            continue
        # 无法解析的行：静默跳过（可能是多行值的延续，已被上面处理）
    return frontmatter, ""


def validate_skill(skill_path):
    """Basic validation of a skill directory."""
    skill_path = Path(skill_path)

    # Check SKILL.md exists
    skill_md = skill_path / 'SKILL.md'
    if not skill_md.exists():
        return False, "SKILL.md not found"

    # Read and validate frontmatter
    content = skill_md.read_text(encoding='utf-8')
    if not content.startswith('---'):
        return False, "No YAML frontmatter found"

    frontmatter, parse_err = parse_frontmatter(content)
    if parse_err:
        return False, parse_err
    if not isinstance(frontmatter, dict) or not frontmatter:
        return False, "Frontmatter must be a non-empty YAML dictionary"

    # Check for unexpected properties (excluding nested keys under metadata)
    unexpected_keys = set(frontmatter.keys()) - ALLOWED_PROPERTIES
    if unexpected_keys:
        return False, (
            f"Unexpected key(s) in SKILL.md frontmatter: {', '.join(sorted(unexpected_keys))}. "
            f"Allowed properties are: {', '.join(sorted(ALLOWED_PROPERTIES))}"
        )

    # Check required fields
    for req in REQUIRED_PROPERTIES:
        if req not in frontmatter:
            return False, f"Missing '{req}' in frontmatter"

    # Extract name for validation
    name = frontmatter.get('name', '')
    if not isinstance(name, str):
        return False, f"Name must be a string, got {type(name).__name__}"
    name = name.strip()
    if name:
        # Check naming convention (kebab-case: lowercase with hyphens)
        if not re.match(r'^[a-z0-9-]+$', name):
            return False, f"Name '{name}' should be kebab-case (lowercase letters, digits, and hyphens only)"
        if name.startswith('-') or name.endswith('-') or '--' in name:
            return False, f"Name '{name}' cannot start/end with hyphen or contain consecutive hyphens"
        # Check name length (max 64 characters per spec)
        if len(name) > 64:
            return False, f"Name is too long ({len(name)} characters). Maximum is 64 characters."

    # Extract and validate description
    description = frontmatter.get('description', '')
    if not isinstance(description, str):
        return False, f"Description must be a string, got {type(description).__name__}"
    description = description.strip()
    if description:
        # Check for angle brackets
        if '<' in description or '>' in description:
            return False, "Description cannot contain angle brackets (< or >)"
        # Check description length (max 1024 characters per spec)
        if len(description) > 1024:
            return False, f"Description is too long ({len(description)} characters). Maximum is 1024 characters."

    # Validate compatibility field if present (optional)
    compatibility = frontmatter.get('compatibility', '')
    if compatibility:
        if not isinstance(compatibility, str):
            return False, f"Compatibility must be a string, got {type(compatibility).__name__}"
        if len(compatibility) > 500:
            return False, f"Compatibility is too long ({len(compatibility)} characters). Maximum is 500 characters."

    return True, "Skill is valid!"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/quick_validate.py <skill_directory>")
        sys.exit(1)

    valid, message = validate_skill(sys.argv[1])
    print(message)
    sys.exit(0 if valid else 1)
