"""Skill 管理工具 — 让 agent 学习、列出和遗忘 skill。

模块导入时通过 ``registry.register()`` 注册。
Skill 存储在 ``<project_root>/skills/``（Path.cwd() / "skills"）下。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from abstract.skills.manager import create_skill, delete_skill, update_skill, write_skill_file, read_skill_file
from abstract.skills.loader import list_skills, load_skill
from abstract.tools.registry import registry, tool_error, tool_result

from system.context import get_runtime_context
from system.pathutils import find_repo_root

logger = logging.getLogger(__name__)


# ── 辅助函数 ──────────────────────────────────────────────────────────


def _skills_dir() -> Path:
    """返回规范的 skill 目录（项目根目录 / skills）。"""
    return (find_repo_root() / "skills").resolve()


def _format_skill_list(skills_dir: Path | None = None) -> dict:
    """返回所有已注册 skill 的格式化列表。"""
    skills: list[dict]
    try:
        skills = list_skills(skills_dir=skills_dir or _skills_dir())
    except Exception:
        return {"error": "Failed to list skills", "skills": []}
    result: list[dict] = []
    for s in skills:
        result.append({
            "name": s.get("name", ""),
            "description": s.get("description", ""),
            "category": s.get("category"),
            "tags": s.get("tags", []),
        })
    return {"skills": result, "total": len(result)}


# ── 工具 handler ────────────────────────────────────────────────────


def _handle_learn_skill(args: dict[str, Any]) -> dict:
    """创建或更新指定名称和内容的 skill，支持多文件写入。"""
    name: str = str(args.get("name", "")).strip()
    content: str = str(args.get("content", "")).strip()
    description: str = str(args.get("description", "")).strip()
    category: str | None = str(args.get("category", "")).strip() or None
    tags: list = args.get("tags", []) or []
    files: list[dict] = args.get("files", []) or []

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
                name,
                skills_dir=_skills_dir(),
                description=description or name,
                category=category,
                content=content,
                tags=tags if isinstance(tags, list) else [str(tags)],
            )
        if payload.get("success"):
            # Write additional files into the skill package
            written: list[dict] = []
            write_errors: list[dict] = []
            for f in files:
                fpath: str = str(f.get("path", "")).strip()
                fcontent: str = str(f.get("content", ""))
                if not fpath:
                    write_errors.append({"error": "file 'path' is required"})
                    continue
                result: dict = write_skill_file(
                    name=name,
                    subpath=fpath,
                    content=fcontent,
                    skills_dir=_skills_dir(),
                )
                if result.get("success"):
                    written.append({"path": fpath})
                else:
                    write_errors.append({"path": fpath, "error": result.get("error")})
            return tool_result(
                created=True,
                name=payload.get("name"),
                path=payload.get("path"),
                files_written=written,
                file_errors=write_errors if write_errors else None,
            )
        return tool_error(payload.get("error", "Unknown error creating skill"))
    except Exception as exc:
        return tool_error(str(exc))


def _handle_list_skills(args: dict[str, Any]) -> dict:
    """列出所有可用 skill。"""
    return _format_skill_list(_skills_dir())


def _handle_forget_skill(args: dict[str, Any]) -> dict:
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


def _handle_recall_skill(args: dict[str, Any]) -> dict:
    """将 skill 的完整内容加载到对话中。"""
    name: str = str(args.get("name", "")).strip()
    if not name:
        return _format_skill_list(_skills_dir())

    try:
        payload: dict = load_skill(name, skills_dir=_skills_dir())
        if payload.get("success"):
            return {
                "name": payload.get("name"),
                "description": payload.get("description"),
                "category": payload.get("category"),
                "content": payload.get("content"),
                "facts": payload.get("facts", []),
                "linked_files": payload.get("linked_files", {}),
                "skill_dir": payload.get("skill_dir"),
            }
        return tool_error(payload.get("error", "Skill not found"))
    except Exception as exc:
        return tool_error(str(exc))


def _handle_write_skill_file(args: dict[str, Any]) -> dict:
    """向已有 skill 包内写入附属文件。"""
    name: str = str(args.get("name", "")).strip()
    path: str = str(args.get("path", "")).strip()
    content: str = str(args.get("content", ""))

    if not name:
        return tool_error("name is required")
    if not path:
        return tool_error("path is required")

    try:
        result: dict = write_skill_file(
            name=name,
            subpath=path,
            content=content,
            skills_dir=_skills_dir(),
        )
        if result.get("success"):
            return tool_result(
                written=True,
                name=name,
                path=result.get("relative_path"),
            )
        return tool_error(result.get("error", "Unknown error"))
    except Exception as exc:
        return tool_error(str(exc))


def _handle_read_skill_file(args: dict[str, Any]) -> dict:
    """读取 skill 包内的附属文件内容。"""
    name: str = str(args.get("name", "")).strip()
    path: str = str(args.get("path", "")).strip()

    if not name:
        return tool_error("name is required")
    if not path:
        return tool_error("path is required")

    try:
        result: dict = read_skill_file(
            name=name,
            subpath=path,
            skills_dir=_skills_dir(),
        )
        if result.get("success"):
            return {
                "name": name,
                "path": result.get("relative_path"),
                "content": result.get("content"),
            }
        return tool_error(result.get("error", "File not found"))
    except Exception as exc:
        return tool_error(str(exc))


def _handle_run_skill_script(args: dict[str, Any]) -> dict:
    """在 skill 包目录下执行 scripts/ 中的脚本并返回结果。"""
    import subprocess  # nosec: intentional for skill scripts

    name: str = str(args.get("name", "")).strip()
    script: str = str(args.get("script", "")).strip()
    script_args: list = args.get("args", []) or []

    if not name:
        return tool_error("name is required")
    if not script:
        return tool_error("script is required")

    try:
        # Resolve skill directory
        from abstract.skills.loader import load_skill as _load

        payload: dict = _load(name, skills_dir=_skills_dir())
        if not payload.get("success"):
            return tool_error(payload.get("error", "Skill not found"))
        skill_dir: str = str(payload.get("skill_dir", ""))
        script_path: Path = Path(skill_dir) / "scripts" / script
        script_path = script_path.resolve()

        # Security: must be inside the skill's scripts/ directory
        skill_resolved: Path = Path(skill_dir).resolve()
        allowed_prefix: Path = skill_resolved / "scripts"
        try:
            script_path.relative_to(allowed_prefix)
        except ValueError:
            return tool_error(
                f"Script '{script}' is not inside {skill_resolved.name}/scripts/"
            )

        if not script_path.exists():
            return tool_error(
                f"Script not found: {skill_resolved.name}/scripts/{script}"
            )
        if not script_path.is_file():
            return tool_error(f"Not a file: {skill_resolved.name}/scripts/{script}")

        cmd: list[str] = [str(script_path)] + [str(a) for a in script_args]
        _timeout = get_runtime_context().tool_timeout
        proc = subprocess.run(
            cmd,
            cwd=str(skill_resolved),
            capture_output=True,
            text=True,
            timeout=_timeout,
        )
        return {
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "exit_code": proc.returncode,
            "success": proc.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return tool_error(f"Script execution timed out ({_timeout}s)")
    except Exception as exc:
        return tool_error(str(exc))


# ── 注册 ─────────────────────────────────────────────────────


registry.register(
    name="learn_skill",
    toolset="skills",
    schema={
        # 创建或更新 skill。Skill 是以目录形式存储在
        # project-root/skills/ 下的可复用知识模块，
        # 包含 SKILL.md 主文档以及可选的 scripts/、references/、
        # templates/、assets/ 等附属文件。
        # 通过 files 参数可一次性写入脚本和参考文档。
        # 用于持久化跨 session 有用的知识。
        # 如果同名 skill 已存在则更新。
        "description": (
            "Create or update a skill. A skill is a reusable knowledge module "
            "stored as a directory under project-root/skills/, "
            "containing a SKILL.md main document and optional scripts/, "
            "references/, templates/, assets/ and other ancillary files. "
            "The files parameter can write scripts and reference docs in one go. "
            "Useful for persisting useful knowledge across sessions. "
            "Updates the skill if one with the same name already exists."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    # Skill 名称（简短，kebab-case）。
                    "description": "Skill name (short, kebab-case).",
                },
                "description": {
                    "type": "string",
                    # 一行描述，说明 skill 的功能。
                    "description": "A one-line description explaining the skill's purpose.",
                },
                "content": {
                    "type": "string",
                    # Skill 的 Markdown 正文。
                    "description": "The Markdown body of the skill.",
                },
                "category": {
                    "type": "string",
                    # 可选分类（如 'utility'、'knowledge'）。
                    "description": "Optional category (e.g. 'utility', 'knowledge').",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    # 可选的筛选标签。
                    "description": "Optional filtering tags.",
                },
                "files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                # 相对于 skill 目录的路径，如 scripts/hello.py
                                "description": "Path relative to the skill directory, e.g. scripts/hello.py",
                            },
                            "content": {
                                "type": "string",
                                # 文件内容。
                                "description": "File content.",
                            },
                        },
                        "required": ["path", "content"],
                    },
                    # 可选。要一同写入 skill 包的附属文件列表（脚本、参考文档等）。
                    "description": "Optional. List of ancillary files (scripts, reference docs, etc.) to write into the skill package.",
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
        # 列出所有可用 skill 的名称和描述。
        "description": "List all available skills' names and descriptions.",
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
        # 按名称删除 skill。用于移除不再相关或有用的 skill。
        "description": "Delete a skill by name. Used to remove skills that are no longer relevant or useful.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    # 要删除的 skill 名称。
                    "description": "The name of the skill to delete.",
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
        # 将 skill 的完整内容加载到当前对话上下文中。
        # 用于在任务匹配某个 skill 描述时按需获取其完整知识。
        # 无参数调用时列出可用 skill。
        "description": (
            "Load the full content of a skill into the current conversation context. "
            "Use this when a task matches a skill's description. "
            "Calling without arguments lists available skills."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    # 要回忆的 skill 名称（省略则列出全部）。
                    "description": "The name of the skill to recall (omit to list all).",
                },
            },
        },
    },
    handler=_handle_recall_skill,
    emoji="🔍",
)


registry.register(
    name="write_skill_file",
    toolset="skills",
    schema={
        # 向已有 skill 包内写入附属文件（如 scripts/、references/ 等）。
        # 用于在创建 skill 后补充脚本、模板、参考文档。
        # path 相对于 skill 目录，如 scripts/hello.py。
        "description": (
            "Write ancillary files (e.g. scripts/, references/) "
            "into an existing skill package. "
            "Used to add scripts, templates, and reference documents "
            "after creating the skill. "
            "path is relative to the skill directory, e.g. scripts/hello.py."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    # Skill 名称。
                    "description": "Skill name.",
                },
                "path": {
                    "type": "string",
                    # 相对于 skill 目录的文件路径，如 scripts/hello.py
                    "description": "File path relative to the skill directory, e.g. scripts/hello.py",
                },
                "content": {
                    "type": "string",
                    # 文件内容。
                    "description": "File content.",
                },
            },
            "required": ["name", "path", "content"],
        },
    },
    handler=_handle_write_skill_file,
    emoji="📝",
    danger_level="write",
)


registry.register(
    name="read_skill_file",
    toolset="skills",
    schema={
        # 读取 skill 包内附属文件的内容（如 scripts/、references/ 等）。
        # 用于查看 skill 包中的脚本代码、参考文档等。
        "description": (
            "Read the content of ancillary files inside a skill package "
            "(e.g. scripts/, references/). "
            "Useful for viewing script code, reference documents, etc. "
            "inside a skill package."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    # Skill 名称。
                    "description": "Skill name.",
                },
                "path": {
                    "type": "string",
                    # 相对于 skill 目录的文件路径，如 scripts/hello.py
                    "description": "File path relative to the skill directory, e.g. scripts/hello.py",
                },
            },
            "required": ["name", "path"],
        },
    },
    handler=_handle_read_skill_file,
    emoji="📖",
)


registry.register(
    name="run_skill_script",
    toolset="skills",
    schema={
        # 执行 skill 包内 scripts/ 目录下的脚本并返回结果。
        # 用于运行 skill 附带的工具脚本。
        # 脚本在 skill 目录上下文下执行，timeout 30 秒。
        "description": (
            "Execute a script from the scripts/ directory inside "
            "a skill package and return the result. "
            "Useful for running utility scripts bundled with a skill. "
            "The script runs in the context of the skill directory "
            "with a 30-second timeout."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    # Skill 名称。
                    "description": "Skill name.",
                },
                "script": {
                    "type": "string",
                    # scripts/ 目录下的脚本文件名，如 hello.py
                    "description": "Script filename under scripts/, e.g. hello.py",
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    # 传递给脚本的命令行参数。
                    "description": "Command-line arguments to pass to the script.",
                },
            },
            "required": ["name", "script"],
        },
    },
    handler=_handle_run_skill_script,
    emoji="▶️",
    danger_level="write",
)