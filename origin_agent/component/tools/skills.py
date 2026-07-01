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
from entity.puretype import ToolDangerLevel

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
    except Exception as exc:
        logger.exception("Failed to list skills: %s", exc)
        return {"error": f"Failed to list skills: {exc}", "skills": []}
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
        # - 小范围修改或追加内容应使用沙箱内置的 edit_file 或 write_file，路径使用 `skills:` 前缀（如 `skills:my-skill/SKILL.md`）。
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
- For small edits or appending content, use the sandbox built-in edit_file or write_file with the `skills:` prefix (e.g. `skills:my-skill/SKILL.md`).

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
                    # 可选分类（如 'utility'、'knowledge'）。
                    "description": "Optional category (e.g. 'utility', 'knowledge').",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    # 可选的筛选标签列表。
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
                    # 可选。要一同写入 skill 包的附属文件列表（脚本、参考文档等）。每项需提供 `path`（相对路径，如 scripts/hello.py）和 `content`（文件内容）。
                    "description": "Optional. List of ancillary files (scripts, reference docs, etc.) to write into the skill package. Each item requires 'path' (relative path, e.g. scripts/hello.py) and 'content' (file content).",
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
        # 列出 project-root/skills/ 下所有可用 skill 的名称和描述。
        #
        # ## 前置条件
        # 无。
        #
        # ## 调用效果
        # 无副作用，纯查询。返回所有已注册 skill 的名称、描述、分类和标签。
        #
        # ## 返回
        # ```json
        # {"skills": [{"name": "...", "description": "...", "category": "...", "tags": [...]}], "total": N}
        # ```
        #
        # ## 何时使用
        # - 查看当前有哪些 skill 可用。
        # - 在调用 recall_skill 之前确认 skill 名称。
        #
        # ## 副作用/注意
        # - 纯查询，无副作用。
        "description": """List the names and descriptions of all available skills under project-root/skills/.

## Prerequisites
None.

## Effect
No side effects, read-only query. Returns the name, description, category, and tags of all registered skills.

## Returns
```json
{"skills": [{"name": "...", "description": "...", "category": "...", "tags": [...]}], "total": N}
```

## When to Use
- Check what skills are currently available.
- Confirm a skill name before calling recall_skill.

## Side Effects / Notes
- Read-only query, no side effects.""",
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
        # 按名称删除 skill。从 project-root/skills/ 下移除整个 skill 目录及其所有附属文件。
        #
        # ## 前置条件
        # 要删除的 skill 必须已存在。删除前必须征得用户明确确认。
        #
        # ## 调用效果
        # 删除指定名称的 skill 目录及其中所有文件。不可恢复。
        #
        # ## 返回
        # ```json
        # {"deleted": true, "name": "my-skill"}
        # ```
        #
        # ## 何时使用
        # - 移除不再相关或有用的 skill。
        # - 清理过时或错误的 skill。
        #
        # ## 副作用/注意
        # - 永久删除文件系统中的 skill 目录，不可恢复。
        # - 删除不存在的 skill 会返回错误。
        "description": """Delete a skill by name. Removes the entire skill directory and all its ancillary files from project-root/skills/.

## Prerequisites
The skill to delete must exist. The user MUST explicitly confirm before deletion.

## Effect
Deletes the named skill directory and all files within it. Irreversible.

## Returns
```json
{"deleted": true, "name": "my-skill"}
```

## When to Use
- Remove skills that are no longer relevant or useful.
- Clean up outdated or erroneous skills.

## Side Effects / Notes
- Permanently deletes the skill directory from the file system; cannot be undone.
- Deleting a non-existent skill returns an error.""",
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
        #
        # ## 前置条件
        # 要加载的 skill 必须已存在。
        #
        # ## 调用效果
        # 若提供 `name`，返回该 skill 的完整内容（SKILL.md 正文、linked_files 等），内容会被注入到对话上下文中。
        # 若不提供 `name`，列出所有可用 skill（等同于 list_skills）。
        #
        # ## 返回
        # 成功时：
        # ```json
        # {"name": "...", "description": "...", "content": "...", "linked_files": {...}, "skill_dir": "..."}
        # ```
        # 无参数时：
        # ```json
        # {"skills": [...], "total": N}
        # ```
        #
        # ## 何时使用
        # - 任务匹配某个 skill 描述时，加载其完整知识到上下文。
        # - 对尚未加载过的 skill 应积极 recall，尤其是提到相关关键词时。
        # - 即使只是觉得某个 skill 可能相关，也应 recall 查看。
        # - 查看 skill 的完整内容（包括附属文件）。
        #
        # ## 副作用/注意
        # - Skill 内容会被注入到当前对话上下文，消耗 token 预算。
        # - 不存在的 skill 返回错误。
        "description": """Load the full content of a skill into the current conversation context.

## Prerequisites
The skill to recall must exist.

## Effect
If `name` is provided, returns the skill's full content (SKILL.md body, linked_files, etc.), which is injected into the conversation context.
If `name` is omitted, lists all available skills (equivalent to list_skills).

## Returns
On success:
```json
{"name": "...", "description": "...", "content": "...", "linked_files": {...}, "skill_dir": "..."}
```
Without arguments:
```json
{"skills": [...], "total": N}
```

## When to Use
- When a task matches a skill's description, load its full knowledge into context.
- Proactively recall skills that have not been loaded yet, especially when related keywords are mentioned.
- If a skill seems potentially relevant, recall it to check.
- View a skill's complete content (including ancillary files).

## Side Effects / Notes
- Skill content is injected into the current conversation context, consuming token budget.
- Recalling a non-existent skill returns an error.""",
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
        #
        # ## 前置条件
        # 目标 skill 必须已存在。此工具用于写入附属文件，不应替代 learn_skill 写入主 SKILL.md。
        #
        # ## 调用效果
        # 在 project-root/skills/<name>/ 目录下创建或覆盖由 `path` 指定的文件。
        # `path` 相对于 skill 根目录（如 `scripts/hello.py` 对应 `project-root/skills/<name>/scripts/hello.py`）。
        # 若文件已存在则覆盖，若父目录不存在则自动创建。
        # 文件内容由 `content` 参数完整决定，不追加、不合并。
        #
        # ## 返回
        # ```json
        # {"written": true, "name": "my-skill", "path": "scripts/hello.py"}
        # ```
        #
        # ## 何时使用
        # - 在创建 skill 后补充脚本、模板、参考文档。
        # - 向已有 skill 添加新的附属文件。
        #
        # ## 副作用/注意
        # - 写入文件系统。
        # - 同名文件会被覆盖。
        # - 不存在的 skill 返回错误。
        # - 不应替代 learn_skill 写入 SKILL.md 主文档。
        "description": """Write ancillary files (e.g. scripts/, references/) into an existing skill package.

## Prerequisites
The target skill must exist. This tool is for ancillary files only; do not use it to write the main SKILL.md (use learn_skill instead).

## Effect
Creates or overwrites the file at `path` under project-root/skills/<name>/.
`path` is relative to the skill root directory (e.g. `scripts/hello.py` → `project-root/skills/<name>/scripts/hello.py`).
If the file already exists it is overwritten; missing parent directories are created automatically.
The file content is determined entirely by the `content` parameter — no appending, no merging.

## Returns
```json
{"written": true, "name": "my-skill", "path": "scripts/hello.py"}
```

## When to Use
- Add scripts, templates, and reference documents after creating the skill.
- Add new ancillary files to an existing skill.

## Side Effects / Notes
- Writes to the file system.
- Existing files with the same name are overwritten.
- Non-existent skills return an error.
- Do not use this to write the SKILL.md main document; use learn_skill instead.""",
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
    danger_level=ToolDangerLevel.write,
)


registry.register(
    name="read_skill_file",
    toolset="skills",
    schema={
        # 读取 skill 包内附属文件的内容（如 scripts/、references/ 等）。
        #
        # ## 前置条件
        # 目标 skill 和文件必须已存在。
        #
        # ## 调用效果
        # 读取 project-root/skills/<name>/<path> 的完整文件内容并返回。
        # `path` 相对于 skill 根目录（如 `scripts/hello.py`）。
        #
        # ## 返回
        # ```json
        # {"name": "my-skill", "path": "scripts/hello.py", "content": "print('hello')"}
        # ```
        #
        # ## 何时使用
        # - 查看 skill 包中的脚本代码、参考文档等附属文件。
        # - 检查 skill 附属文件的具体内容。
        #
        # ## 副作用/注意
        # - 无副作用，纯查询。
        # - 不存在的 skill 或文件返回错误。
        "description": """Read the content of ancillary files inside a skill package (e.g. scripts/, references/).

## Prerequisites
The target skill and file must exist.

## Effect
Reads and returns the full content of project-root/skills/<name>/<path>.
`path` is relative to the skill root directory (e.g. `scripts/hello.py`).

## Returns
```json
{"name": "my-skill", "path": "scripts/hello.py", "content": "print('hello')"}
```

## When to Use
- View script code, reference documents, and other ancillary files inside a skill package.
- Inspect the specific content of a skill's ancillary files.

## Side Effects / Notes
- No side effects, read-only query.
- Non-existent skills or files return an error.""",
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
        #
        # ## 前置条件
        # 目标 skill 和 scripts/ 下的脚本文件必须已存在。
        #
        # ## 调用效果
        # 在 skill 目录上下文中执行 `scripts/<script>`，可选传递 `args` 作为命令行参数。
        # 脚本必须在 skill 的 scripts/ 目录内，否则拒绝执行。
        # 默认超时 30 秒，超时返回错误。
        #
        # ## 返回
        # ```json
        # {"stdout": "...", "stderr": "...", "exit_code": 0, "success": true}
        # ```
        #
        # ## 何时使用
        # - 运行 skill 附带的工具脚本。
        # - 执行 skill 包中预定义的自动化流程。
        #
        # ## 副作用/注意
        # - 脚本可能产生文件系统副作用。
        # - 安全限制：脚本必须位于 skill 的 scripts/ 子目录内，禁止路径遍历。
        # - 默认 30 秒超时。
        # - 不存在的 skill 或脚本返回错误。
        "description": """Execute a script from the scripts/ directory inside a skill package and return the result.

## Prerequisites
The target skill and the script file under scripts/ must exist.

## Effect
Executes `scripts/<script>` in the context of the skill directory, optionally passing `args` as command-line arguments.
The script must reside inside the skill's scripts/ directory; otherwise execution is rejected.
Default timeout is 30 seconds; timed-out executions return an error.

## Returns
```json
{"stdout": "...", "stderr": "...", "exit_code": 0, "success": true}
```

## When to Use
- Run utility scripts bundled with a skill.
- Execute predefined automation workflows inside a skill package.

## Side Effects / Notes
- Scripts may produce file system side effects.
- Security: scripts must be inside the skill's scripts/ subdirectory; path traversal is blocked.
- Default 30-second timeout.
- Non-existent skills or scripts return an error.""",
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
    danger_level=ToolDangerLevel.write,
)