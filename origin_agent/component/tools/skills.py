"""Skill 管理工具 — 让 agent 学习、列出和遗忘 skill。

模块导入时通过 ``registry.register()`` 注册。
Skill 存储在 ``<project_root>/skills/``（Path.cwd() / "skills"）下。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from abstract.skills.manager import create_skill, update_skill, write_skill_file
from abstract.skills.loader import list_skills, load_skill
from abstract.tools.registry import registry, tool_error, tool_result

from system.pathutils import find_repo_root

logger = logging.getLogger(__name__)


# ── 辅助函数 ──────────────────────────────────────────────────────────


def _skills_dir() -> Path:
    """返回规范的 skill 目录（项目根目录 / skills）。"""
    return (find_repo_root() / "skills").resolve()


def _format_skill_list(skills_dir: Path | None = None) -> dict:
    """返回所有已注册 skill 的格式化列表（含沙箱路径）。"""
    skills: list[dict]
    try:
        skills = list_skills(skills_dir=skills_dir or _skills_dir())
    except Exception as exc:
        logger.exception("Failed to list skills: %s", exc)
        return {"error": f"Failed to list skills: {exc}", "skills": []}
    result: list[dict] = []
    for s in skills:
        rel_path: str = s.get("path", "")
        sandbox_path: str = (
            f"skills:{Path(rel_path).parent.as_posix()}/" if rel_path else ""
        )
        result.append({
            "name": s.get("name", ""),
            "description": s.get("description", ""),
            "category": s.get("category"),
            "tags": s.get("tags", []),
            "path": sandbox_path,
        })
    return {"skills": result, "total": len(result)}


# ── 工具 handler ────────────────────────────────────────────────────


def _handle_learn_skill(args: dict[str, Any]) -> dict:
    """创建或更新指定名称和内容的 skill，支持多文件写入。"""
    name: str = str(args.get("name", "")).strip()
    content: str = str(args.get("content", "")).strip()
    description: str = str(args.get("description", "")).strip()
    category: str = str(args.get("category", "")).strip()
    tags: list = args.get("tags", []) or []
    files: list[dict] = args.get("files", []) or []

    if not name:
        return tool_error("name is required")
    if not content:
        return tool_error("content is required")
    if not category:
        return tool_error("category is required")
    if not tags or not isinstance(tags, list) or not all(str(t).strip() for t in tags):
        return tool_error("tags is required as a non-empty array of strings")

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





# ── 注册 ─────────────────────────────────────────────────────


registry.register(
    name="CreateSkill",
    toolset="skills",
    schema={
        # 创建新 skill 或对已有 skill 进行较大程度的更改。Skill 是以目录形式存储在
        # project-root/skills/ 下的可复用知识模块，包含 SKILL.md 主文档及可选的
        # scripts/、references/、templates/、assets/ 等附属文件。
        #
        # ## 前置条件
        # 必须确实了解了一个具有模板意义的工作流程，其中的细节对其他类似任务具有指导意义。
        # 不应为琐碎或一次性操作创建 skill。
        #
        # ## 调用效果
        # 若同名 skill 不存在则创建，已存在则覆盖更新（适合较大程度的内容替换）。
        # 通过 `files` 参数可一次性写入附属文件（脚本、参考文档等）。
        #
        # ## 返回
        # ```json
        # {"created": true, "name": "my-skill", "path": "/path/to/skills/my-skill", "files_written": [{"path": "scripts/hello.py"}], "file_errors": null}
        # ```
        #
        # ## 何时使用
        # - 创建全新 skill。
        # - 对已有 skill 的主体内容进行较大程度更改。
        # - 小范围修改或追加内容应使用沙箱内置的 PatchEdit 或 Write，路径使用 `skills:` 前缀（如 `skills:my-skill/SKILL.md`）。
        #
        # ## 副作用/注意
        # - 写入 project-root/skills/ 下的文件系统。
        # - 同名 skill 会被覆盖更新，谨慎使用。
        # - `name` 推荐使用简短 kebab-case。
        "description": """Create a new skill or make significant changes to an existing one. A skill is a reusable knowledge module stored as a directory under project-root/skills/, containing a SKILL.md main document and optional scripts/, references/, templates/, assets/ and other ancillary files.

## Prerequisites
The agent must have genuinely understood a workflow that has template value, where the details are instructive for other similar tasks. Do not create skills for trivial or one-off operations.

## Effect
Creates a new skill if the name does not exist, or overwrites (updates) if one with the same name already exists — suitable for major content replacement.
The `files` parameter can write ancillary files (scripts, reference docs, etc.) in one go.

## Returns
```json
{"created": true, "name": "my-skill", "path": "/path/to/skills/my-skill", "files_written": [{"path": "scripts/hello.py"}], "file_errors": null}
```

## When to Use
- Create a brand-new skill.
- Make significant changes to an existing skill's main content.
- For small edits or appending content, use the sandbox built-in PatchEdit or Write with the `skills:` prefix (e.g. `skills:my-skill/SKILL.md`).

## Side Effects / Notes
- Writes to the file system under project-root/skills/.
- Skills with the same name are overwritten; use with caution.
- `name` should use short kebab-case.""",
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
                    # 必填分类（如 'utility'、'knowledge'）。skill 创建于 skills/<category>/<name>/。
                    "description": "Required category (e.g. 'utility', 'knowledge'). The skill is created under skills/<category>/<name>/.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    # 必填的标签列表（非空数组）。
                    "description": "Required filtering tags (non-empty array).",
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
                    # 可选。要一同写入 skill 包的附属文件列表（脚本、参考文档等）。每项需提供 `path`（相对路径，如 scripts/hello.py）和 `content`（文件内容）。
                    "description": "Optional. List of ancillary files (scripts, reference docs, etc.) to write into the skill package. Each item requires 'path' (relative path, e.g. scripts/hello.py) and 'content' (file content).",
                },
            },
            "required": ["name", "content", "category", "tags"],
        },
    },
    handler=_handle_learn_skill,
    emoji="🧠",
)


registry.register(
    name="RecallSkill",
    toolset="skills",
    schema={
        # 加载 skill 的完整内容，或在无参数时列举全部可用 skill。
        #
        # ## 前置条件
        # 无。
        #
        # ## 调用效果
        # - 无 `name`：列举分支。返回所有已注册 skill 的 {name, description, category, tags, path}，
        #   其中 path 为 skill 目录的沙箱路径（如 `skills:utility/foo/`），可直接用于 Read / CreateSkill / Delete。
        # - 有 `name`：加载分支。返回该 skill 的完整内容（SKILL.md 正文、linked_files 等结构化信息），注入对话上下文。
        #
        # ## 返回
        # 列举分支：
        # ```json
        # {"skills": [{"name": "...", "description": "...", "category": "...", "tags": [...], "path": "skills:..."}], "total": N}
        # ```
        # 加载分支：
        # ```json
        # {"name": "...", "description": "...", "category": "...", "content": "...", "linked_files": {...}, "skill_dir": "..."}
        # ```
        #
        # ## 何时使用
        # - 先列举确认可用的 skill 及其路径。
        # - 任务匹配某个 skill 时，传入 name 加载完整知识。
        # - 对尚未加载过的 skill 应积极加载，尤其是提到相关关键词时。
        #
        # ## 副作用/注意
        # - 加载分支会把 skill 内容注入对话上下文，消耗 token 预算。
        # - 加载不存在的 skill 返回错误。
        "description": """Load the full content of a skill, or list all available skills when called without a name.

## Prerequisites
None.

## Effect
- Without `name` (list branch): returns {name, description, category, tags, path} for every registered skill, where `path` is the sandbox path of the skill directory (e.g. `skills:utility/foo/`) — directly usable with Read / CreateSkill / Delete.
- With `name` (load branch): returns the skill's full content (SKILL.md body, linked_files, etc.) as structured information injected into the conversation context.

## Returns
List branch:
```json
{"skills": [{"name": "...", "description": "...", "category": "...", "tags": [...], "path": "skills:..."}], "total": N}
```
Load branch:
```json
{"name": "...", "description": "...", "category": "...", "content": "...", "linked_files": {...}, "skill_dir": "..."}
```

## When to Use
- List available skills (and their sandbox paths) before selecting one.
- Load a skill's full knowledge into context when a task matches its description.
- Proactively load skills that have not been loaded yet, especially when related keywords are mentioned.

## Side Effects / Notes
- The load branch injects skill content into the conversation context, consuming token budget.
- Loading a non-existent skill returns an error.""",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    # 要加载的 skill 名称（省略则列举全部 skill 及其沙箱路径）。
                    "description": "The name of the skill to load (omit to list all skills with their sandbox paths).",
                },
            },
        },
    },
    handler=_handle_recall_skill,
    emoji="🔍",
)


