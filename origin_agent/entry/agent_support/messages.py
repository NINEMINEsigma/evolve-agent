"""AgentLoop 消息构建辅助工具。"""

from __future__ import annotations

import importlib.util
import logging
import sys
import types
from pathlib import Path
from typing import * # type: ignore

from system.prompt import build_system_prompt
from entity.puretype import Role
from entity.messages import History

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


def collect_hooks_context(
    hooks: list[dict],
    session_id: str,
    workspace: str,
    runtime_ctx: "RuntimeContext | None" = None,
) -> str:
    """收集 custom_hooks 的实时上下文。新 hook 可通过 **kwargs 接收 runtime_ctx。"""
    parts: list[str] = []
    for hook in hooks:
        try:
            tag = _call_hook_with_runtime_ctx(hook["tag_fn"], session_id, workspace, runtime_ctx)
            if tag:
                msg = _call_hook_with_runtime_ctx(hook["msg_fn"], session_id, workspace, runtime_ctx)
                if msg:
                    part = f"<|im_{tag}_start|>{msg}<|im_{tag}_end|>"
                    parts.append(part)
        except Exception:
            logger.warning("Failed to collect hook context", exc_info=True)
    result = "\n".join(parts)
    logger.info("Collected hooks context (%d chars): %s", len(result), result[:500])
    return result


def build_agent_system_prompt(ctx: RuntimeContext, skill_blocks: list[str]) -> list[str]:
    """构建 Agent 使用的 system prompt 段落列表。"""
    return build_system_prompt(
        mode=ctx.mode,
        extra_blocks=skill_blocks,
        workspace=ctx.workspace,
        agentspace=str(ctx.agentspace),
        fork_path=str(ctx.fork_path),
        fix_fork_path=str(ctx.fix_path) if ctx.fix_path else "",
        fix_log_path=str(ctx.fix_log_path or ""),
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


def build_turn_messages(
    system_prompts: list[str],
    history: History,
    current_character_agent: str,
    session_id: str,
    workspace: str,
    memory_ctx: str,
    hooks: list[dict],
    runtime_ctx: "RuntimeContext | None" = None,
) -> tuple[list[dict[str, Any]], str]:
    """构建当前回合发送给 LLM 的消息列表。返回 (messages, fixator_context)。"""
    messages: list[dict[str, Any]] = [
        {"role": Role.SYSTEM, "content": sp} for sp in system_prompts
    ]

    # 通过 History 获取当前 agent 的 OpenAI 格式视图
    history_messages = history.to_openai(current_character_agent)

    # 找到最后一条 user 消息的位置
    last_user_idx = -1
    for i, msg in enumerate(history_messages):
        if msg.get("role") == Role.USER:
            last_user_idx = i

    # 分别收集 hook_message（仅发送）和 hook_fixator（发送 + 历史保留）内容
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
                    fixator_parts.append(f"<|im_{tag}_fixator_start|>\n{fix}\n<|im_{tag}_fixator_end|>")
        except Exception:
            logger.warning("Failed to collect hook context", exc_info=True)

    hooks_context = "\n".join(hooks_parts)
    fixator_context = "\n".join(fixator_parts)
    logger.info("Appending hooks_context (%s) to user message; fixator_context (%s) will be persisted as message_suffix", hooks_context, fixator_context)

    for i, msg in enumerate(history_messages):
        if i == last_user_idx and msg.get("role") == Role.USER:
            hooked_msg = dict(msg)
            hooked_content = hooked_msg.get("content", "")

            # 发送用的消息：附加 memory + hooks_context（非持久化）。
            # fixator_context 通过 message_suffix 持久化到历史，History.to_openai 会自动追加。
            send_extras: list[str] = []
            if memory_ctx:
                send_extras.append(f"<|im_memory_context_start|>\n{memory_ctx}\n<|im_memory_context_end|>")
            if hooks_context:
                send_extras.append(hooks_context)

            if send_extras:
                if isinstance(hooked_content, list):
                    appended = False
                    for block in reversed(hooked_content):
                        if isinstance(block, dict) and block.get("type") == "text":
                            block["text"] = str(block.get("text", "")) + "\n" + "\n".join(send_extras)
                            appended = True
                            break
                    if not appended:
                        hooked_content.append({"type": "text", "text": "\n".join(send_extras)})
                else:
                    hooked_content = str(hooked_content) + "\n" + "\n".join(send_extras)
                hooked_msg["content"] = hooked_content

            messages.append(hooked_msg)
        else:
            messages.append(msg)

    return messages, fixator_context


def build_full_history_messages(
    system_prompts: list[str],
    history: History,
    current_character_agent: str,
) -> list[dict[str, Any]]:
    """构建包含 system prompts 和完整历史的消息列表。"""
    messages: list[dict[str, Any]] = [
        {"role": Role.SYSTEM, "content": sp} for sp in system_prompts
    ]
    messages.extend(history.to_openai(current_character_agent))
    return messages