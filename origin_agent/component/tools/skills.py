"""Skill 管理工具 — 让 agent 学习、列出和遗忘 skill。

模块导入时通过 ``registry.register()`` 注册。
Skill 存储在 ``<project_root>/skills/``（Path.cwd() / "skills"）下。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from abstract.skills.manager import create_skill, delete_skill, update_skill
from abstract.skills.loader import list_skills, load_skill
from abstract.tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)

# ── 常量 ────────────────────────────────────────────────────────

_SKILLS_DIR: Path = Path("skills")


# ── 辅助函数 ──────────────────────────────────────────────────────────


def _skills_dir() -> Path:
    """返回规范的 skill 目录（项目根目录 / skills）。"""
    return _SKILLS_DIR.resolve()


def _format_skill_list(skills_dir: Path | None = None) -> str:
    """返回所有已注册 skill 的格式化列表。"""
    skills: list[dict]
    try:
        skills = list_skills(skills_dir=skills_dir or _skills_dir())
    except Exception:
        return json.dumps(
            {"error": "Failed to list skills", "skills": []},
            ensure_ascii=False,
        )
    result: list[dict] = []
    for s in skills:
        result.append({
            "name": s.get("name", ""),
            "description": s.get("description", ""),
            "category": s.get("category"),
            "tags": s.get("tags", []),
        })
    return json.dumps({"skills": result, "total": len(result)}, ensure_ascii=False)


# ── 工具 handler ────────────────────────────────────────────────────


def _handle_learn_skill(args: Dict[str, Any]) -> str:
    """创建或更新指定名称和内容的 skill。"""
    name: str = str(args.get("name", "")).strip()
    content: str = str(args.get("content", "")).strip()
    description: str = str(args.get("description", "")).strip()
    category: str | None = str(args.get("category", "")).strip() or None
    tags: list = args.get("tags", []) or []

    if not name:
        return tool_error("name is required")
    if not content:
        return tool_error("content is required")

    try:
        payload: dict = create_skill(
            name=name,
            skills_dir=_skills_dir(),
            description=description or name,
            category=category,
            content=content,
            tags=tags if isinstance(tags, list) else [str(tags)],
        )
        if not payload.get("success"):
            payload = update_skill(
                name=name,
                skills_dir=_skills_dir(),
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
    """列出所有可用 skill。"""
    return _format_skill_list(_skills_dir())


def _handle_forget_skill(args: Dict[str, Any]) -> str:
    """按名称删除 skill。"""
    name: str = str(args.get("name", "")).strip()
    if not name:
        return tool_error("name is required")

    try:
        result: dict = delete_skill(name, skills_dir=_skills_dir())
        if result.get("success"):
            return tool_result(deleted=True, name=name)
        return tool_error(result.get("error", "Unknown error deleting skill"))
    except Exception as exc:
        return tool_error(str(exc))


def _handle_recall_skill(args: Dict[str, Any]) -> str:
    """将 skill 的完整内容加载到对话中。"""
    name: str = str(args.get("name", "")).strip()
    if not name:
        return _format_skill_list(_skills_dir())

    try:
        payload: dict = load_skill(name, skills_dir=_skills_dir())
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


# ── 注册 ─────────────────────────────────────────────────────


registry.register(
    name="learn_skill",
    toolset="skills",
    schema={
        "description": (
            "创建或更新 skill。Skill 是以 SKILL.md 文件形式存储在 "
            "project-root/skills/ 目录下的可复用知识模块。"
            "用于持久化跨 session 有用的知识。"
            "如果同名 skill 已存在则更新。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill 名称（简短，kebab-case）。",
                },
                "description": {
                    "type": "string",
                    "description": "一行描述，说明 skill 的功能。",
                },
                "content": {
                    "type": "string",
                    "description": "Skill 的 Markdown 正文。",
                },
                "category": {
                    "type": "string",
                    "description": "可选分类（如 'utility'、'knowledge'）。",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选的筛选标签。",
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
        "description": "列出所有可用 skill 的名称和描述。",
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
        "description": "按名称删除 skill。用于移除不再相关或有用的 skill。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "要删除的 skill 名称。",
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
            "将 skill 的完整内容加载到对话中。"
            "用于刷新对 skill 细节的记忆。"
            "无参数调用时列出可用 skill。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "要回忆的 skill 名称（省略则列出全部）。",
                },
            },
        },
    },
    handler=_handle_recall_skill,
    emoji="🔍",
)