"""子 Agent 编排器 — 按主会话管理子 Agent 生命周期。

职责：
- 每个主会话拥有独立的子 Agent 上下文
- 并发控制（活跃上限 + FIFO 等待队列）
- 周期定时器（空闲检测 + 结果收集 + 消息注入）
- 工具操作代理（chat / approve / stop）
- 优雅关闭
"""

from __future__ import annotations

import asyncio
import json
import logging
import time as _time_module
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from entity.constant import (
    MAX_TOOL_TURNS,
    SUBAGENT_IDLE_TRIGGER_SECONDS,
    SUBAGENT_MAX_ACTIVE,
)
from entity.puretype import Role, ToolAvailability
from abstract.tools.registry import registry as tool_registry
from system.context import get_runtime_context
from entry.parent_agent_loop import ParentAgentLoop
from system.convert import as_enum

from .context import SubRuntimeContext, build_subagent_context
from .loop import SUB_MESSAGE_SEPARATOR, SubAgentLoop, format_user_message

logger = logging.getLogger(__name__)


class WaitingEntry:
    """等待队列条目。"""

    def __init__(
        self,
        session_id: str,
        profile: dict[str, Any],
        temperature: float,
        initial_prompt: str,
        user_name: str,
        message_type: str,
        history_path: str = "",
    ) -> None:
        self.session_id: str = session_id
        self.profile: dict[str, Any] = profile
        self.temperature: float = temperature
        self.initial_prompt: str = initial_prompt
        self.user_name: str = user_name
        self.message_type: str = message_type
        self.history_path: str = history_path


class _OrchestratorContext:
    """单个主会话的子 Agent 上下文。"""

    def __init__(self, parent_session_id: str, agent_loop: ParentAgentLoop) -> None:
        self._parent_session_id: str = parent_session_id
        self._agent_loop: ParentAgentLoop = agent_loop
        self._active: dict[str, SubAgentLoop] = {}
        self._active_task: dict[str, asyncio.Task] = {}
        self._waiting_queue: deque[WaitingEntry] = deque()
        self._subagent_names: dict[str, str] = {}  # session_id -> registry_name
        self._background_task: asyncio.Task | None = None
        self._interrupted: bool = False
        self._shutting_down: bool = False

    # ── 启动 ────────────────────────────────────────────────────────

    async def launch(
        self,
        profile: dict[str, Any],
        temperature: float,
        initial_prompt: str,
        user_name: str,
        message_type: str,
        parent_session_id: str,
        history_path: str | None = None,
    ) -> dict[str, Any]:
        """启动一个子 Agent 会话。"""
        name = profile.get("_name", "")

        # 同一主会话下同一 subagent 只能有一个活跃或排队实例
        for active_sid, active_name in self._subagent_names.items():
            if active_name == name:
                sub = self._active.get(active_sid)
                if sub is not None and not sub.completed and not sub.terminated:
                    return {
                        "success": False,
                        "error": f"Sub-agent '{name}' is already active in this parent session.",
                    }
        for i, entry in enumerate(self._waiting_queue):
            if entry.profile.get("_name") == name:
                return {
                    "success": False,
                    "error": (
                        f"Sub-agent '{name}' is already queued (position {i + 1}). "
                        "Please wait for it to activate or stop it first."
                    ),
                }

        session_id = f"{parent_session_id}_{uuid.uuid4().hex[:12]}"

        # 检查上限
        if len(self._active) >= SUBAGENT_MAX_ACTIVE:
            # 进入等待队列
            self._waiting_queue.append(
                WaitingEntry(
                    session_id=session_id,
                    profile=profile,
                    temperature=temperature,
                    initial_prompt=initial_prompt,
                    user_name=user_name,
                    message_type=message_type,
                    history_path=history_path or "",
                )
            )
            logger.info(
                "Subagent queued | parent=%s session=%s position=%d",
                parent_session_id, session_id, len(self._waiting_queue),
            )
            return {
                "success": True,
                "session_id": session_id,
                "waiting": True,
                "queue_position": len(self._waiting_queue),
            }

        # 立即启动
        await self._start_subagent(
            session_id, profile, temperature,
            initial_prompt, user_name, message_type, history_path,
        )
        return {
            "success": True,
            "session_id": session_id,
            "waiting": False,
        }

    # ── 交互 ────────────────────────────────────────────────────────

    def _drain_outbox(self, sub: SubAgentLoop) -> list[str]:
        """清空并返回子 Agent 的发件箱内容。"""
        outbox = sub.outbox
        sub._outbox.clear()
        return list(outbox)

    async def chat_user_direct(self, session_id: str, message: str, co_recipients: list[str] | None = None) -> dict[str, Any]:
        """最终用户直接向子会话发送消息（支持 FIFO 排队）。"""
        sub = self._active.get(session_id)
        if sub is None:
            for entry in self._waiting_queue:
                if entry.session_id == session_id:
                    return {
                        "success": False,
                        "session_id": session_id,
                        "error": "Sub-agent is queued (not yet active).",
                    }
            return {
                "success": False,
                "session_id": session_id,
                "error": "Sub-agent not found (may have been stopped or completed).",
            }
        sub.inject_parent_message(message, "User", "user_direct", co_recipients)
        wrapped = format_user_message("User", "user_direct", message, co_recipients)
        await self._push_subagent_ws(
            session_id,
            self._subagent_names.get(session_id, ""),
            {"role": "user", "content": wrapped},
        )
        return {"success": True, "session_id": session_id}

    async def chat(
        self,
        session_id: str,
        message: str,
        user_name: str,
        message_type: str,
        co_recipients: list[str] | None = None,
    ) -> dict[str, Any]:
        """父 Agent 向子 Agent 发送消息。"""
        sub = self._active.get(session_id)
        if sub is None:
            # 检查等待队列
            for entry in self._waiting_queue:
                if entry.session_id == session_id:
                    return {
                        "success": False,
                        "session_id": session_id,
                        "error": "Sub-agent is queued (not yet active). Cannot chat.",
                    }
            return {
                "success": False,
                "session_id": session_id,
                "error": "Sub-agent not found (may have been stopped or completed).",
            }
        # 硬拦截：本轮响应尚未完成时禁止 chat（防止父 Agent 疯狂催促）
        if sub.round_active:
            return {
                "success": False,
                "session_id": session_id,
                "error": "Sub-agent is still generating its current response. Wait for [subagent-result] before calling chat_subagent.",
            }
        # 先收取子 Agent 的反馈；如果还有未送达的反馈，让父 Agent 先查看，不要急于发新消息
        outbox = self._drain_outbox(sub)
        if outbox:
            return {
                "success": False,
                "session_id": session_id,
                "feedback": outbox,
                "note": "Sub-agent has already produced feedback that you have not yet received. Please review the feedback first, then decide whether and how to reply via chat_subagent.",
            }
        # 没有未送达反馈，正常发送
        sub.inject_parent_message(message, user_name, message_type, co_recipients)
        # 推送父→子消息到前端子会话面板
        wrapped = format_user_message(user_name, message_type, message, co_recipients)
        await self._push_subagent_ws(
            session_id,
            self._subagent_names.get(session_id, ""),
            {"role": "user", "content": wrapped},
        )
        return {
            "success": True,
            "session_id": session_id,
            "feedback": None,
        }

    async def approve(self, session_id: str, decisions: list[dict[str, Any]]) -> dict[str, Any]:
        """审批子 Agent 的工具调用。"""
        sub = self._active.get(session_id)
        if sub is None:
            return {
                "success": False,
                "session_id": session_id,
                "error": "Sub-agent not found (may have been stopped or completed).",
            }
        results = sub.approve_tools(decisions)
        # 审批后顺手收集一次 outbox
        outbox = self._drain_outbox(sub)
        return {
            "success": True,
            "session_id": session_id,
            "processed": len(results),
            "results": results,
            "feedback": outbox if outbox else None,
        }

    async def stop(self, session_id: str) -> dict[str, Any]:
        """停止子 Agent 会话。"""
        # 检查是否在等待队列中
        for i, entry in enumerate(self._waiting_queue):
            if entry.session_id == session_id:
                del self._waiting_queue[i]
                logger.info("Subagent removed from queue | session=%s", session_id)
                return {
                    "success": True,
                    "session_id": session_id,
                    "session_path": None,
                    "promoted": [],
                    "note": "Sub-agent was queued (not yet active). No history to save.",
                }

        sub = self._active.get(session_id)
        if sub is None:
            return {
                "success": False,
                "session_id": session_id,
                "error": "Sub-agent not found.",
            }

        if sub.completed:
            return {
                "success": False,
                "session_id": session_id,
                "error": "Sub-agent has already completed.",
            }

        # 强制停止
        sub.stop()

        # 保存会话历史 — 文件路径包含注册名便于定位
        name = self._subagent_names.get(session_id, "")
        session_path = self._history_path(session_id, name=name)
        try:
            sub.save_history(session_path)
        except Exception as exc:
            logger.exception("Failed to save subagent history for %s: %s", session_id, exc)
            return {
                "success": False,
                "session_id": session_id,
                "error": f"Failed to save history: {exc}",
            }

        # 清理
        self._active.pop(session_id, None)
        task = self._active_task.pop(session_id, None)
        if task and not task.done():
            task.cancel()

        logger.info("Subagent stopped | session=%s path=%s", session_id, session_path)

        # 推送 terminated 状态到前端面板
        await self._push_subagent_ws(
            session_id,
            self._subagent_names.get(session_id, ""),
            {"role": "terminated", "content": "sub-agent stopped"},
            status_override="terminated",
        )

        # 级联出队：一出一入
        promoted = await self._activate_next()

        return {
            "success": True,
            "session_id": session_id,
            "session_path": str(session_path),
            "promoted": promoted,
        }

    # ── 生命周期 ────────────────────────────────────────────────────

    def interrupt(self) -> None:
        self._interrupted = True

    def resume(self) -> None:
        self._interrupted = False

    async def terminate_parent(self) -> None:
        """父 Agent 会话终结时停止所有子 Agent。"""
        logger.info("Parent terminated: stopping all subagents | parent=%s", self._parent_session_id)
        for session_id in list(self._active.keys()):
            await self.stop(session_id)
        self._waiting_queue.clear()

    def get_snapshot(self) -> dict[str, dict[str, Any]]:
        """返回所有活跃子会话的快照（供前端刷新时拉取）。"""
        snap: dict[str, dict[str, Any]] = {}
        for session_id, sub in self._active.items():
            feedback: list[dict[str, Any]] = []
            for entry in sub._history:
                role = entry.get("role")
                if role == Role.SYSTEM:
                    continue
                if role == Role.USER:
                    feedback.append({"role": "user", "content": str(entry.get("content", ""))})
                elif role == Role.ASSISTANT:
                    content = str(entry.get("content", ""))
                    reasoning = entry.get("reasoning_content")
                    if content:
                        item: dict[str, Any] = {"role": "assistant", "content": content}
                        if reasoning:
                            item["reasoning"] = str(reasoning)
                        feedback.append(item)
                    elif reasoning:
                        feedback.append({"role": "reasoning", "reasoning": str(reasoning)})
                    tool_calls = entry.get("tool_calls")
                    if tool_calls and isinstance(tool_calls, list):
                        for tc in tool_calls:
                            fn = (tc.get("function") or {}) if isinstance(tc, dict) else {}
                            feedback.append({
                                "role": "tool_call",
                                "tool_call_id": str(tc.get("id", "") if isinstance(tc, dict) else ""),
                                "tool_name": str(fn.get("name", "")),
                                "tool_args": fn.get("arguments") if isinstance(fn, dict) else {},
                            })
                elif role == Role.TOOL:
                    feedback.append({
                        "role": "tool_result",
                        "tool_call_id": str(entry.get("tool_call_id", "")),
                        "content": str(entry.get("content", "")),
                    })
            status = "completed" if sub.completed else ("terminated" if sub.terminated else "running")
            snap[session_id] = {
                "session_id": session_id,
                "name": self._subagent_names.get(session_id, ""),
                "status": status,
                "feedback": feedback,
                "pending_approvals": sub.pending_approvals_info,
            }
        return snap

    async def shutdown(self) -> None:
        """关闭本上下文的所有活跃子 Agent。"""
        self._shutting_down = True
        if self._background_task and not self._background_task.done():
            self._background_task.cancel()
        logger.info("Subagent context shutdown | parent=%s active=%d", self._parent_session_id, len(self._active))
        for session_id in list(self._active.keys()):
            await self.stop(session_id)
        self._waiting_queue.clear()

    # ── 内部 ────────────────────────────────────────────────────────

    async def _push_subagent_ws(
        self,
        session_id: str,
        name: str,
        event: dict[str, Any] | None = None,
        *,
        status_override: str | None = None,
    ) -> None:
        """推送一条结构化事件到前端面板。"""
        try:
            from gateway.server import push_subagent_update
            sub = self._active.get(session_id)
            if status_override is not None:
                status = status_override
            elif sub is None:
                status = "terminated"
            elif sub.completed:
                status = "completed"
            elif sub.terminated:
                status = "terminated"
            else:
                status = "running"
            feedback: list[dict[str, Any]] = [event] if event else []
            pending = sub.pending_approvals_info if sub is not None else []
            removed = sub is None
            await push_subagent_update(
                parent_session_id=self._parent_session_id,
                subagent_session_id=session_id,
                subagent_name=name,
                status=status,
                feedback=feedback,
                pending_approvals=pending,
                removed=removed,
            )
        except Exception as exc:
            logger.warning("WS push for subagent %s failed: %s", session_id, exc, exc_info=True)

    async def _start_subagent(
        self,
        session_id: str,
        profile: dict[str, Any],
        temperature: float,
        initial_prompt: str,
        user_name: str,
        message_type: str,
        history_path: str | None = None,
    ) -> None:
        """创建 SubAgentLoop 并以 asyncio.Task 启动。"""
        parent_ctx = get_runtime_context()
        ctx = await build_subagent_context(profile, temperature, parent_ctx)

        tools = self._build_tool_set()

        def _push_msg(event: dict[str, Any]) -> None:
            asyncio.create_task(self._push_subagent_ws(
                session_id, profile.get("_name", ""), event,
            ))

        loop = SubAgentLoop(ctx, session_id, tools, MAX_TOOL_TURNS, on_message=_push_msg, parent_session_id=self._parent_session_id, name=profile.get("_name", ""))
        self._active[session_id] = loop
        self._subagent_names[session_id] = profile.get("_name", "")

        if history_path:
            loaded: list[dict[str, Any]] = []
            with open(history_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entry: dict[str, Any] = json.loads(line)
                    if not isinstance(entry, dict):
                        continue
                    role = as_enum(entry.get("role"), Role)
                    if role is None:
                        continue
                    if role == Role.SYSTEM:
                        continue
                    entry["role"] = role
                    loaded.append(entry)
            loop._history = loaded
            for entry in loaded:
                role = entry.get("role")
                if role == Role.USER:
                    await self._push_subagent_ws(
                        session_id, profile.get("_name", ""),
                        {"role": "user", "content": str(entry.get("content", ""))},
                    )
                elif role == Role.ASSISTANT:
                    content = str(entry.get("content", ""))
                    if content:
                        await self._push_subagent_ws(
                            session_id, profile.get("_name", ""),
                            {"role": "assistant", "content": content},
                        )
                    for tc in (entry.get("tool_calls") or []):
                        fn = (tc.get("function") or {}) if isinstance(tc, dict) else {}
                        await self._push_subagent_ws(
                            session_id, profile.get("_name", ""),
                            {
                                "role": "tool_call",
                                "tool_call_id": str(tc.get("id", "") if isinstance(tc, dict) else ""),
                                "tool_name": str(fn.get("name", "")),
                                "tool_args": fn.get("arguments") if isinstance(fn, dict) else {},
                            },
                        )
                elif role == Role.TOOL:
                    await self._push_subagent_ws(
                        session_id, profile.get("_name", ""),
                        {
                            "role": "tool_result",
                            "tool_call_id": str(entry.get("tool_call_id", "")),
                            "content": str(entry.get("content", "")),
                        },
                    )
            logger.info(
                "Subagent history loaded | session=%s entries=%d",
                session_id, len(loop._history),
            )

        # 立即推送 WS 通知前端面板
        await self._push_subagent_ws(
            session_id,
            profile.get("_name", ""),
            {"role": "status", "content": "started"},
            status_override="running",
        )

        # 推送 initial_prompt 到前端面板
        wrapped_initial = format_user_message(user_name, message_type, initial_prompt)
        await self._push_subagent_ws(
            session_id,
            profile.get("_name", ""),
            {"role": "user", "content": wrapped_initial},
        )

        task = asyncio.create_task(loop.run(initial_prompt, user_name, message_type), name=f"subagent-{session_id[:16]}")
        self._active_task[session_id] = task

        logger.info(
            "Subagent started | parent=%s session=%s model=%s tools=%d",
            self._parent_session_id, session_id, ctx.model, len(tools),
        )

    async def _activate_next(self) -> list[dict[str, str]]:
        """从等待队列取出一个启动。"""
        if not self._waiting_queue:
            return []
        entry = self._waiting_queue.popleft()
        await self._start_subagent(
            entry.session_id,
            entry.profile,
            entry.temperature,
            entry.initial_prompt,
            entry.user_name,
            entry.message_type,
            entry.history_path or None,
        )
        logger.info("Subagent activated from queue | session=%s", entry.session_id)
        return [{"session_id": entry.session_id, "subagent_name": entry.profile.get("name", "")}]

    def _build_tool_set(self) -> list[dict[str, Any]]:
        """构建子 Agent 的工具集 — 仅包含 availability 包含 SUBAGENT 或 EVERY 的工具。"""
        return tool_registry.get_definitions_for_availability(ToolAvailability.SUBAGENT)

    def _get_agent_loop(self) -> ParentAgentLoop | None:
        """解析当前父 session 对应的真实 ParentAgentLoop。

        Orchestrator 在启动时拿到的是 __bootstrap__ loop，而每个真实 session
        都由 SessionManager 维护独立的 loop，因此需要动态解析。
        """
        try:
            from system.application import Application
            sm = Application.current().session_manager
            if sm is not None:
                loop = sm.get_loop(self._parent_session_id)
                if loop is not None:
                    return loop
        except Exception:
            logger.warning(
                "Failed to resolve real ParentAgentLoop for parent=%s; falling back to bootstrap loop",
                self._parent_session_id,
                exc_info=True,
            )
        return self._agent_loop

    async def _cycle_loop(self) -> None:
        """后台周期定时器 — 收集子 Agent 结果并注入父 Agent。"""
        while not self._shutting_down:
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                return

            if self._interrupted or self._shutting_down:
                continue

            loop = self._get_agent_loop()
            if loop is None:
                continue

            last_idle = loop._last_idle_time
            if not isinstance(last_idle, dict):
                continue

            idle_sec = _time_module.monotonic() - last_idle.get(self._parent_session_id, 0)

            # 每轮推送倒计时到前端
            if self._active:
                remaining = max(0, int(SUBAGENT_IDLE_TRIGGER_SECONDS - idle_sec))
                for session_id in self._active:
                    name = self._subagent_names.get(session_id, "")
                    await self._push_subagent_ws(
                        session_id,
                        name,
                        {"role": "countdown", "content": str(remaining)},
                    )

            if idle_sec < SUBAGENT_IDLE_TRIGGER_SECONDS:
                continue

            # 检查是否有父 Agent 正在处理本会话消息
            if loop.is_processing():
                continue

            # 收集
            await self._collect_and_inject(loop)

    async def _collect_and_inject(self, loop: ParentAgentLoop) -> None:
        """收集所有活跃子 Agent 的 outbox 和待审批队列，注入父 Agent。"""
        messages: list[str] = []

        for session_id, sub in list(self._active.items()):
            parts: list[str] = []
            parts.append(f"session_id: {session_id}")

            outbox = sub.outbox
            sub._outbox.clear()
            if outbox:
                merged = SUB_MESSAGE_SEPARATOR.join(outbox)
                parts.append(f"feedback:\n  {merged}")

            pending = sub.pending_approvals_info
            if pending:
                parts.append("pending_approvals:")
                for p in pending:
                    parts.append(f"  - tool_call_id: {p['tool_call_id']}")
                    parts.append(f"    tool_name: {p['tool_name']}")
                    parts.append(f"    arguments: {json.dumps(p['arguments'], ensure_ascii=False)}")

            if len(parts) > 1:
                messages.append("\n".join(parts))

            status = "completed" if sub.completed else ("terminated" if sub.terminated else "running")
            try:
                from gateway.server import push_subagent_update
                await push_subagent_update(
                    parent_session_id=self._parent_session_id,
                    subagent_session_id=session_id,
                    subagent_name=self._subagent_names.get(session_id, ""),
                    status=status,
                    feedback=[],
                    pending_approvals=pending,
                )
            except Exception as exc:
                logger.debug("WS push failed for subagent %s: %s", session_id, exc)

        if not messages:
            return

        full_message = (
            "[subagent-result]\n"
            "This is a sub-agent feedback message visible only to you (the parent agent); "
            "the end user does not directly see it. "
            "The sub-agent's 'user' is you — it sends feedback, asks questions, "
            "and requests tool approvals through you. "
            "You decide how to respond: approve/reject tools, send chat messages, "
            "or stop the sub-agent when its task is complete.\n\n"
        ) + "\n\n".join(messages)

        try:
            await loop.process_message(full_message)
            logger.debug("Subagent result injected to parent | parent=%s entries=%d", self._parent_session_id, len(messages))
        except Exception as exc:
            logger.exception(
                "Failed to inject subagent result for parent=%s: %s",
                self._parent_session_id, exc,
            )

    @staticmethod
    def _history_path(session_id: str, name: str = "") -> Path:
        """子 Agent 会话历史的存储路径。"""
        ctx = get_runtime_context()
        dir = ctx.agentspace / "subagents"
        if name:
            dir = dir / name
        dir.mkdir(parents=True, exist_ok=True)
        return dir / f"{session_id}.jsonl"


class SubAgentOrchestrator:
    """按主会话管理多个子 Agent 上下文。"""

    def __init__(self) -> None:
        self._agent_loop: ParentAgentLoop | None = None
        self._contexts: dict[str, _OrchestratorContext] = {}

    def set_agent_loop(self, agent_loop: ParentAgentLoop) -> None:
        """注入父 AgentLoop 引用。"""
        self._agent_loop = agent_loop

    def _get_context(self, parent_session_id: str) -> _OrchestratorContext:
        """获取或创建指定父会话的上下文。"""
        if parent_session_id not in self._contexts:
            assert self._agent_loop is not None, "set_agent_loop() must be called before any context operation"
            self._contexts[parent_session_id] = _OrchestratorContext(parent_session_id, self._agent_loop)
            # 启动后台周期任务
            self._contexts[parent_session_id]._background_task = asyncio.create_task(
                self._contexts[parent_session_id]._cycle_loop(),
                name=f"subagent-cycle-{parent_session_id[:16]}",
            )
        return self._contexts[parent_session_id]

    # ── 公共代理方法 ─────────────────────────────────────────────────

    async def launch(self, parent_session_id: str, **kwargs: Any) -> dict[str, Any]:
        return await self._get_context(parent_session_id).launch(parent_session_id=parent_session_id, **kwargs)

    async def chat_user_direct(self, parent_session_id: str, session_id: str, message: str, co_recipients: list[str] | None = None) -> dict[str, Any]:
        return await self._get_context(parent_session_id).chat_user_direct(session_id, message, co_recipients)

    async def chat(self, parent_session_id: str, session_id: str, message: str, user_name: str, message_type: str, co_recipients: list[str] | None = None) -> dict[str, Any]:
        return await self._get_context(parent_session_id).chat(session_id, message, user_name, message_type, co_recipients)

    async def approve(self, parent_session_id: str, session_id: str, decisions: list[dict[str, Any]]) -> dict[str, Any]:
        return await self._get_context(parent_session_id).approve(session_id, decisions)

    async def stop(self, parent_session_id: str, session_id: str) -> dict[str, Any]:
        return await self._get_context(parent_session_id).stop(session_id)

    def interrupt(self, parent_session_id: str) -> None:
        self._get_context(parent_session_id).interrupt()

    def resume(self, parent_session_id: str) -> None:
        self._get_context(parent_session_id).resume()

    async def terminate_parent(self, parent_session_id: str) -> None:
        ctx = self._contexts.get(parent_session_id)
        if ctx is not None:
            await ctx.terminate_parent()

    def get_snapshot(self, parent_session_id: str) -> dict[str, dict[str, Any]]:
        ctx = self._contexts.get(parent_session_id)
        if ctx is None:
            return {}
        return ctx.get_snapshot()

    async def shutdown_all(self) -> None:
        """关闭所有上下文的子 Agent。"""
        for ctx in list(self._contexts.values()):
            await ctx.shutdown()
        self._contexts.clear()

    async def shutdown_parent(self, parent_session_id: str) -> None:
        """关闭指定父会话的所有子 Agent 并清理上下文。"""
        ctx = self._contexts.pop(parent_session_id, None)
        if ctx is not None:
            await ctx.shutdown()
