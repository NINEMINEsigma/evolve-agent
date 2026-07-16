"""AgentLoop 消息构建辅助工具。"""

from __future__ import annotations

import importlib.util
import logging
import sys
import types
from pathlib import Path
from typing import * # type: ignore

from system.prompt import build_system_prompt
from entity.puretype import Role, ToolAvailability
from entity.messages import History, BaseMessage, CharacterSystemMessage

if TYPE_CHECKING:
    from system.context import RuntimeContext

logger = logging.getLogger(__name__)


def load_message_hooks(repo_root: Path, logger: logging.Logger) -> list[dict]:
    """加载 custom_hooks 中的消息扩展 hook。"""
    hooks: list[dict] = []
    hooks_dir = repo_root / "custom_hooks"
    logger.info("Loading message hooks from %s", hooks_dir)
    if not hooks_dir.is_dir():
        logger.info("Hooks directory does not exist: %s", hooks_dir)
        return hooks

    # 创建/复用 custom_hooks 父包，使子模块处于隔离命名空间，
    # 便于 easysave 通过 importlib.import_module 恢复其中定义的类。
    parent_pkg = sys.modules.get("custom_hooks")
    if parent_pkg is None:
        parent_pkg = types.ModuleType("custom_hooks")
        parent_pkg.__path__ = [str(hooks_dir)]
        sys.modules["custom_hooks"] = parent_pkg

    for fpath in sorted(hooks_dir.glob("*.py")):
        if fpath.name.startswith("_"):
            continue
        try:
            module_name = f"custom_hooks.{fpath.stem}"
            spec = importlib.util.spec_from_file_location(module_name, fpath)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)
            if (
                hasattr(mod, "hook_tag_name")
                and (hasattr(mod, "hook_message") or hasattr(mod, "hook_fixator"))
            ):
                tag_fn = mod.hook_tag_name
                msg_fn = mod.hook_message if hasattr(mod, "hook_message") else None
                fixator_fn = mod.hook_fixator if hasattr(mod, "hook_fixator") else None
                if callable(tag_fn) and (callable(msg_fn) or callable(fixator_fn)):
                    hooks.append({
                        "tag_fn": tag_fn,
                        "msg_fn": msg_fn if callable(msg_fn) else None,
                        "fixator_fn": fixator_fn if callable(fixator_fn) else None,
                    })
                    logger.info("Loaded message hook: %s", fpath.name)
                else:
                    logger.info("Skipping %s: hook attributes are not callable", fpath.name)
            else:
                logger.info("Skipping %s: missing hook_tag_name or hook_message/hook_fixator", fpath.name)
        except Exception:
            logger.warning("Failed to load message hook %s", fpath, exc_info=True)
    logger.info("Total message hooks loaded: %d", len(hooks))
    return hooks


def _call_hook_with_runtime_ctx(fn, session_id: str, workspace: str, runtime_ctx: "RuntimeContext | None"):
    """调用 hook 函数，优先传入 runtime_ctx；旧签名不兼容时回退到两参数调用。"""
    try:
        return fn(session_id=session_id, workspace=workspace, runtime_ctx=runtime_ctx)
    except TypeError as exc:
        msg = str(exc)
        if "unexpected keyword argument" in msg or "got an unexpected keyword argument" in msg:
            return fn(session_id, workspace)
        raise


def _collect_hook_parts(
    hooks: list[dict],
    session_id: str,
    workspace: str,
    runtime_ctx: "RuntimeContext | None" = None,
) -> tuple[list[str], list[str]]:
    """分别收集 hook_message（非持久化）和 hook_fixator（持久化）的原始片段。"""
    hooks_parts: list[str] = []
    fixator_parts: list[str] = []
    for hook in hooks:
        try:
            tag = _call_hook_with_runtime_ctx(hook["tag_fn"], session_id, workspace, runtime_ctx)
            if not tag:
                continue
            if callable(hook.get("msg_fn")):
                msg = _call_hook_with_runtime_ctx(hook["msg_fn"], session_id, workspace, runtime_ctx)
                if msg:
                    hooks_parts.append(f"<|im_{tag}_start|>{msg}<|im_{tag}_end|>")
            if callable(hook.get("fixator_fn")):
                fix = _call_hook_with_runtime_ctx(hook["fixator_fn"], session_id, workspace, runtime_ctx)
                if fix:
                    fixator_parts.append(f"<|im_{tag}_fixator_start|>{fix}<|im_{tag}_fixator_end|>")
        except Exception:
            logger.warning("Failed to collect hook context", exc_info=True)
    return hooks_parts, fixator_parts


def collect_all_hooks_context(
    hooks: list[dict],
    session_id: str,
    workspace: str,
    runtime_ctx: "RuntimeContext | None" = None,
) -> tuple[str, str]:
    """一次性收集 custom_hooks 的 hooks_context 和 fixator_context。

    只遍历 hooks 一次，避免重复调用同一个 hook 的 tag_fn 导致状态/计时器紊乱。
    """
    hooks_parts, fixator_parts = _collect_hook_parts(hooks, session_id, workspace, runtime_ctx)
    hooks_context = "\n".join(hooks_parts)
    fixator_context = "\n".join(fixator_parts)
    logger.info(
        "Collected all hooks context | hooks=%d chars, fixator=%d chars",
        len(hooks_context), len(fixator_context),
    )
    return hooks_context, fixator_context


def build_agent_system_prompt(
    ctx: RuntimeContext,
    skill_blocks: list[str],
    tool_availability_scope: ToolAvailability = ToolAvailability.MAIN,
) -> list[str]:
    """构建 Agent 使用的 system prompt 段落列表。"""
    return build_system_prompt(
        mode=ctx.mode,
        extra_blocks=skill_blocks,
        workspace=ctx.workspace,
        agentspace=str(ctx.agentspace),
        fork_path=str(ctx.fork_path),
        fix_fork_path=str(ctx.fix_path) if ctx.fix_path else "",
        fix_log_path=str(ctx.fix_log_path or ""),
        tool_availability_scope=tool_availability_scope,
    )


def collect_skill_prompts(skills_dir: Path | str = Path("skills")) -> list[str]:
    """生成 skill 名称和描述清单，避免全量内容注入 system prompt。"""
    blocks: list[str] = []
    try:
        from abstract.skills.loader import list_skills

        skills: list[dict] = list_skills(skills_dir=Path(skills_dir))
        if skills:
            lines: list[str] = [
                "Available skills (use list_skills to see details, use recall_skill to load one):",
                "",
            ]
            for s in skills:
                name: str = s.get("name", "")
                description: str = s.get("description", "")
                line = f"- {name}"
                if description:
                    line += f": {description}"
                lines.append(line)
            blocks.append("\n".join(lines))
        return blocks
    except Exception as e:
        logger.exception("Failed to collect skill prompts: %s", e)
        return []


def build_full_history_messages(
    system_prompts: list[str],
    history: History,
    current_character_agent: str,
) -> list[BaseMessage]:
    """构建包含 system prompts 和完整历史的消息列表。

    假设调用方已经把 hooks_context / memory_ctx 等非持久化内容通过
    history.last_user_message.dynamic_message_suffix 注入；本函数只负责
    system prompt 与 History.get_messages 的拼接。
    """
    messages: list[BaseMessage] = [
        CharacterSystemMessage(role=Role.SYSTEM, character_name=current_character_agent, content=sp) for sp in system_prompts
    ]
    messages.extend(history.get_messages(current_character_agent=current_character_agent))
    return messages
