"""AgentLoop 消息构建辅助工具。"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any, Dict, List

from system.prompt import build_system_prompt


def load_message_hooks(repo_root: Path, logger: logging.Logger) -> list[dict]:
    """加载 custom_hooks 中的消息扩展 hook。"""
    hooks: list[dict] = []
    hooks_dir = repo_root / "custom_hooks"
    if not hooks_dir.is_dir():
        return hooks

    for fpath in sorted(hooks_dir.glob("*.py")):
        if fpath.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(fpath.stem, fpath)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            tag_fn = getattr(mod, "hook_tag_name", None)
            msg_fn = getattr(mod, "hook_message", None)
            if callable(tag_fn) and callable(msg_fn):
                hooks.append({"tag_fn": tag_fn, "msg_fn": msg_fn})
        except Exception:
            logger.warning("Failed to load message hook %s", fpath, exc_info=True)
    return hooks


def collect_hooks_context(hooks: list[dict], session_id: str, workspace: str) -> str:
    """收集 custom_hooks 的实时上下文。"""
    parts: list[str] = []
    for hook in hooks:
        try:
            tag = hook["tag_fn"](session_id, workspace)
            if tag:
                msg = hook["msg_fn"](session_id, workspace)
                if msg:
                    parts.append(f"<|im_{tag}_start|>{msg}<|im_{tag}_end|>")
        except Exception:
            pass
    return "\n".join(parts)


def build_agent_system_prompt(ctx: Any, skill_blocks: list[str]) -> str:
    """构建 AgentLoop 使用的 system prompt。"""
    return build_system_prompt(
        mode=ctx.mode,
        extra_blocks=skill_blocks,
        lang="zh",
        workspace=ctx.workspace,
        agentspace=str(ctx.agentspace),
        fork_path=str(ctx.fork_path),
        fix_fork_path=str(ctx.fix_path) if ctx.fix_path else "",
        fix_log_path=str(ctx.fix_log_path or ""),
    )


def build_turn_messages(
    system_prompt: str,
    history: List[Dict[str, Any]],
    session_id: str,
    workspace: str,
    memory_ctx: str,
    hooks: list[dict],
) -> List[Dict[str, Any]]:
    """构建当前回合发送给 LLM 的消息列表。"""
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
    ]

    for i, msg in enumerate(history):
        if i == len(history) - 1 and msg.get("role") == "user":
            hooked_msg = dict(msg)
            hooked_content = str(hooked_msg.get("content", ""))

            if memory_ctx:
                hooked_content += f"\n<|im_memory_context_start|>\n{memory_ctx}\n<|im_memory_context_end|>"

            hooks_context = collect_hooks_context(hooks, session_id, workspace)
            if hooks_context:
                hooked_content += hooks_context

            hooked_msg["content"] = hooked_content
            messages.append(hooked_msg)
        else:
            messages.append(msg)

    return messages


def build_full_history_messages(
    system_prompt: str,
    history: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """构建包含 system prompt 和完整历史的消息列表。"""
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
    ]
    messages.extend(history)
    return messages