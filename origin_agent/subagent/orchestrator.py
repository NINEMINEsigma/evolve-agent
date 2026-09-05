"""子 Agent 编排器 — 按主会话管理子 Agent 生命周期。

职责：
- 每个主会话拥有独立的子 Agent 上下文
- 并发控制（活跃上限 + FIFO 等待队列）
- 事件驱动 waiter（结果收集 + 消息注入，由 _start_subagent/_start_taskagent 启动）
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
    SUBAGENT_MAX_ACTIVE,
    SYSTEM_CHARACTER_NAME,
    USER_CHARACTER_NAME,
    History_Version as __History_Version__,
)
from entity.messages import CharacterConversationMessage, ToolResultMessage
from entity.puretype import Role, ToolAvailability, AgentConfig, ToolDangerLevel
from abstract.tools.registry import registry as tool_registry
from system.context import get_runtime_context
from system.templates import read_template
from entry.parent_agent_loop import ParentAgentLoop
from entry.base_agent_loop import IMainSessionLoop

from .context import SubRuntimeContext, build_subagent_context, build_taskagent_context
from .loop import SUB_MESSAGE_SEPARATOR, SubAgentLoop, format_user_message
from .taskloop import TaskAgentLoop

logger = logging.getLogger(__name__)


class WaitingEntry:
    """等待队列条目。"""

    def __init__(
        self,
        session_id: str,
        name: str,
        profile: AgentConfig,
        temperature: float,
        initial_prompt: str,
        user_name: str,
        message_type: str,
        history_path: str = "",
    ) -> None:
        self.session_id: str = session_id
        self.name: str = name
        self.profile: AgentConfig = profile
        self.temperature: float = temperature
        self.initial_prompt: str = initial_prompt
        self.user_name: str = user_name
        self.message_type: str = message_type
        self.history_path: str = history_path


class _OrchestratorContext:
    """单个主会话的子 Agent 上下文。"""

    def __init__(self, parent_session_id: str, agent_loop: IMainSessionLoop) -> None:
        self._parent_session_id: str = parent_session_id
        self._agent_loop: IMainSessionLoop = agent_loop
        self._active: dict[str, SubAgentLoop] = {}
        self._active_task: dict[str, asyncio.Task] = {}
        self._waiting_queue: deque[WaitingEntry] = deque()
        self._subagent_names: dict[str, str] = {}  # session_id -> registry_name
        self._waiter_tasks: dict[str, asyncio.Task] = {}  # SP-5 D4：per-subagent event waiter
        self._interrupted: bool = False
        self._shutting_down: bool = False

    # ── 启动 ────────────────────────────────────────────────────────

    async def launch(
        self,
        name: str,
        profile: AgentConfig,
        temperature: float,
        initial_prompt: str,
        user_name: str,
        message_type: str,
        parent_session_id: str,
        history_path: str | None = None,
    ) -> dict[str, Any]:
        """启动一个子 Agent 会话。"""
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
            if entry.name == name:
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
                    name=name,
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
            session_id, name, profile, temperature,
            initial_prompt, user_name, message_type, history_path,
        )
        return {
            "success": True,
            "session_id": session_id,
            "waiting": False,
        }

    # ── taskagent 启动/停止 ─────────────────────────────────────────

    async def launch_taskagent(
        self,
        parent_session_id: str,
        prompt: str,
        temperature: float,
    ) -> dict[str, Any]:
        """启动一次性 taskagent。"""
        session_id = f"{parent_session_id}_{uuid.uuid4().hex[:12]}"

        # 检查上限
        if len(self._active) >= SUBAGENT_MAX_ACTIVE:
            # taskagent 不进等待队列——直接拒绝
            return {
                "success": False,
                "error": f"Active sub-agent limit reached ({SUBAGENT_MAX_ACTIVE}). Stop some sub-agents first.",
            }

        await self._start_taskagent(session_id, prompt, temperature)
        return {
            "success": True,
            "session_id": session_id,
            "waiting": False,
        }

    async def _start_taskagent(
        self,
        session_id: str,
        prompt: str,
        temperature: float,
    ) -> None:
        """创建 TaskAgentLoop 并以 asyncio.Task 启动。"""
        parent_ctx = get_runtime_context()
        ctx = await build_taskagent_context(parent_ctx, temperature)

        tools = self._build_task_tool_set()

        def _push_msg(event: dict[str, Any]) -> None:
            asyncio.create_task(self._push_subagent_ws(
                session_id, "taskagent", event,
                interactive=False,
            ))

        loop = TaskAgentLoop(
            ctx, session_id, tools, MAX_TOOL_TURNS,
            on_message=_push_msg,
            parent_session_id=self._parent_session_id,
            parent_character_agent=self._agent_loop.current_character_agent,
            name="taskagent",
        )
        self._active[session_id] = loop
        self._subagent_names[session_id] = "taskagent"

        # 推送 WS 通知前端面板
        await self._push_subagent_ws(
            session_id,
            "taskagent",
            {"role": "status", "content": "started"},
            status_override="running",
            interactive=False,
        )

        # 推送 initial_prompt 到前端面板
        wrapped_initial = format_user_message(
            self._agent_loop.current_character_agent, "direct", prompt,
        )
        await self._push_subagent_ws(
            session_id,
            "taskagent",
            {"role": "user", "content": wrapped_initial,
             "character_name": self._agent_loop.current_character_agent},
            interactive=False,
        )

        task = asyncio.create_task(
            loop.run(prompt, self._agent_loop.current_character_agent, "direct"),
            name=f"taskagent-{session_id[:16]}",
        )
        self._active_task[session_id] = task
        # SP-5 D4：启动 per-subagent 事件驱动 waiter
        self._waiter_tasks[session_id] = asyncio.create_task(
            self._subagent_waiter(session_id, loop),
            name=f"subagent-waiter-{session_id[:16]}",
        )

        logger.info(
            "Taskagent started | parent=%s session=%s model=%s tools=%d",
            self._parent_session_id, session_id, ctx.model, len(tools),
        )

    async def stop_taskagent(self, session_id: str) -> dict[str, Any]:
        """强制停止 taskagent — 不保存历史。"""
        sub = self._active.get(session_id)
        if sub is None:
            return {
                "success": False,
                "session_id": session_id,
                "error": "Task-agent not found.",
            }

        if sub.completed:
            return {
                "success": False,
                "session_id": session_id,
                "error": "Task-agent already completed.",
            }

        # 强制停止
        sub.stop()

        # 清理（不保存历史）
        self._active.pop(session_id, None)
        task = self._active_task.pop(session_id, None)
        if task and not task.done():
            task.cancel()
        self._subagent_names.pop(session_id, None)
        # SP-5 D4：清理 waiter task
        waiter = self._waiter_tasks.pop(session_id, None)
        if waiter and not waiter.done():
            waiter.cancel()

        logger.info("Taskagent stopped | session=%s", session_id)

        # 推送 terminated 状态到前端
        await self._push_subagent_ws(
            session_id,
            "taskagent",
            {"role": "terminated", "content": "task-agent stopped"},
            status_override="terminated",
            interactive=False,
        )

        # 级联出队
        await self._activate_next()

        return {
            "success": True,
            "session_id": session_id,
        }

    # ── 交互 ────────────────────────────────────────────────────────

    def _drain_outbox(self, sub: SubAgentLoop) -> list[str]:
        """清空并返回子 Agent 的发件箱内容。"""
        return sub.get_outbox()

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
        sub.inject_parent_message(
            message, "User", "user_direct", co_recipients, character_name=USER_CHARACTER_NAME
        )
        wrapped = format_user_message("User", "user_direct", message, co_recipients)
        await self._push_subagent_ws(
            session_id,
            self._subagent_names.get(session_id, ""),
            {"role": "user", "content": wrapped, "character_name": USER_CHARACTER_NAME},
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
                "_note": "Sub-agent has already produced feedback that you have not yet received. Please review the feedback first, then decide whether and how to reply via chat_subagent.",
            }
        # 没有未送达反馈，正常发送
        character_name = self._agent_loop.current_character_agent
        sub.inject_parent_message(
            message, user_name, message_type, co_recipients, character_name=character_name
        )
        # 推送父→子消息到前端子会话面板
        wrapped = format_user_message(user_name, message_type, message, co_recipients)
        await self._push_subagent_ws(
            session_id,
            self._subagent_names.get(session_id, ""),
            {"role": "user", "content": wrapped, "character_name": character_name},
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
                    "_note": "Sub-agent was queued (not yet active). No history to save.",
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
        # SP-5 D4：清理 waiter task
        waiter = self._waiter_tasks.pop(session_id, None)
        if waiter and not waiter.done():
            waiter.cancel()

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

    def get_snapshot(self) -> dict[str, dict[str, Any]]:
        # TODO: msg.content没有多模态
        """返回所有活跃子会话的快照（供前端刷新时拉取）。"""
        snap: dict[str, dict[str, Any]] = {}
        for session_id, sub in self._active.items():
            feedback: list[dict[str, Any]] = []
            for msg in sub.history.iter_messages():
                if msg.role == Role.SYSTEM:
                    continue
                if msg.role == Role.USER:
                    feedback.append({
                        "role": "user",
                        "content": str(msg.content),
                        "character_name": getattr(msg, "character_name", None) or USER_CHARACTER_NAME,
                    })
                elif msg.role == Role.ASSISTANT:
                    content = str(msg.content)
                    reasoning = msg.reasoning if isinstance(msg, CharacterConversationMessage) else None
                    character_name = getattr(msg, "character_name", None)
                    if content:
                        item: dict[str, Any] = {
                            "role": "assistant",
                            "content": content,
                            "character_name": character_name,
                        }
                        if reasoning:
                            item["reasoning"] = str(reasoning)
                        feedback.append(item)
                    elif reasoning:
                        feedback.append({
                            "role": "reasoning",
                            "reasoning": str(reasoning),
                            "character_name": character_name,
                        })
                    if isinstance(msg, CharacterConversationMessage) and msg.tool_calls:
                        for tc in msg.tool_calls:
                            feedback.append({
                                "role": "tool_call",
                                "tool_call_id": tc.id,
                                "tool_name": tc.function.name,
                                "tool_args": tc.function.arguments,
                                "character_name": character_name,
                            })
                elif msg.role == Role.TOOL and isinstance(msg, ToolResultMessage):
                    feedback.append({
                        "role": "tool_result",
                        "tool_call_id": msg.tool_call_id,
                        "content": str(msg.content),
                        "character_name": getattr(msg, "character_name", None),
                    })
            status = "completed" if sub.completed else ("terminated" if sub.terminated else "running")
            snap[session_id] = {
                "session_id": session_id,
                "name": self._subagent_names.get(session_id, ""),
                "status": status,
                "feedback": feedback,
                "pending_approvals": sub.pending_approvals_info,
                "interactive": not isinstance(sub, TaskAgentLoop),
            }
        return snap

    async def shutdown(self) -> None:
        """关闭本上下文的所有活跃子 Agent。"""
        self._shutting_down = True
        # SP-5 D4：取消所有 waiter task
        for waiter in self._waiter_tasks.values():
            if not waiter.done():
                waiter.cancel()
        self._waiter_tasks.clear()
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
        interactive: bool | None = None,
    ) -> None:
        """推送一条结构化事件到前端面板。

        interactive 为 None 时自动推断：TaskAgentLoop → False，其他 → True。
        """
        try:
            from gateway.server import push_subagent_update
            sub = self._active.get(session_id)
            if interactive is None:
                interactive = not isinstance(sub, TaskAgentLoop)
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
                interactive=interactive,
            )
        except Exception as exc:
            logger.warning("WS push for subagent %s failed: %s", session_id, exc, exc_info=True)

    async def _start_subagent(
        self,
        session_id: str,
        name: str,
        profile: AgentConfig,
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
                session_id, name, event,
            ))

        loop = SubAgentLoop(
            ctx, session_id, tools, MAX_TOOL_TURNS,
            on_message=_push_msg,
            parent_session_id=self._parent_session_id,
            parent_character_agent=self._agent_loop.current_character_agent,
            name=name,
        )
        self._active[session_id] = loop
        self._subagent_names[session_id] = name

        if history_path:
            from easysave import load
            from entity.typeref import make_config
            from entity.messages import History, CharacterConversationMessage, ToolResultMessage

            path = Path(history_path)
            # TODO: 不存在应该失败, 实际上不应该静默吞没错误并成功开始
            if path.exists():
                try:
                    loaded_history = load(__History_Version__, make_config(path), History, ignore_missing_fields=True)
                    if isinstance(loaded_history, History):
                        loaded_history.remove_unpaired_tool_calls()
                        loaded_history.normalize_legacy_tool_results()
                        loop.load_history(loaded_history)
                    else:
                        logger.warning("Loaded subagent history is not History instance: %s", type(loaded_history))
                        loop.load_history(History())
                except Exception as exc:
                    logger.warning("Failed to load subagent history from %s: %s", history_path, exc)
                    loop.load_history(History())
            else:
                loop.load_history(History())

            for msg in loop.history.iter_messages():
                if msg.role == Role.USER:
                    await self._push_subagent_ws(
                        session_id, name,
                        {"role": "user", "content": str(msg.content)},
                    )
                elif msg.role == Role.ASSISTANT:
                    content = str(msg.content)
                    if content:
                        await self._push_subagent_ws(
                            session_id, name,
                            {"role": "assistant", "content": content},
                        )
                    if isinstance(msg, CharacterConversationMessage) and msg.tool_calls:
                        for tc in msg.tool_calls:
                            await self._push_subagent_ws(
                                session_id, name,
                                {
                                    "role": "tool_call",
                                    "tool_call_id": tc.id,
                                    "tool_name": tc.function.name,
                                    "tool_args": tc.function.arguments,
                                },
                            )
                elif msg.role == Role.TOOL and isinstance(msg, ToolResultMessage):
                    await self._push_subagent_ws(
                        session_id, name,
                        {
                            "role": "tool_result",
                            "tool_call_id": msg.tool_call_id,
                            "content": str(msg.content),
                        },
                    )
            logger.info(
                "Subagent history loaded | session=%s entries=%d",
                session_id, loop.history.count,
            )

        # 立即推送 WS 通知前端面板
        await self._push_subagent_ws(
            session_id,
            name,
            {"role": "status", "content": "started"},
            status_override="running",
        )

        # 推送 initial_prompt 到前端面板
        wrapped_initial = format_user_message(user_name, message_type, initial_prompt)
        initial_character_name = USER_CHARACTER_NAME if message_type == "user_direct" else self._agent_loop.current_character_agent
        await self._push_subagent_ws(
            session_id,
            name,
            {"role": "user", "content": wrapped_initial, "character_name": initial_character_name},
        )

        task = asyncio.create_task(loop.run(initial_prompt, user_name, message_type), name=f"subagent-{session_id[:16]}")
        self._active_task[session_id] = task
        # SP-5 D4：启动 per-subagent 事件驱动 waiter
        self._waiter_tasks[session_id] = asyncio.create_task(
            self._subagent_waiter(session_id, loop),
            name=f"subagent-waiter-{session_id[:16]}",
        )

        logger.info(
            "Subagent started | parent=%s session=%s model=%s tools=%d",
            self._parent_session_id, session_id, ctx.model, len(tools),
        )

    async def _activate_next(self) -> list[dict[str, str]]:
        """从等待队列取出一个启动。"""
        if self._shutting_down:
            return []
        if not self._waiting_queue:
            return []
        entry = self._waiting_queue.popleft()
        await self._start_subagent(
            entry.session_id,
            entry.name,
            entry.profile,
            entry.temperature,
            entry.initial_prompt,
            entry.user_name,
            entry.message_type,
            entry.history_path or None,
        )
        logger.info("Subagent activated from queue | session=%s", entry.session_id)
        return [{"session_id": entry.session_id, "subagent_name": entry.name}]

    def _build_tool_set(self) -> list[dict[str, Any]]:
        """构建子 Agent 的工具集 — 仅包含 availability 包含 SUBAGENT 或 EVERY 的工具。"""
        return tool_registry.get_definitions_for_availability(ToolAvailability.SUBAGENT)

    def _build_task_tool_set(self) -> list[dict[str, Any]]:
        """构建 taskagent 工具集 — 仅 TASKAGENT 作用域 + safe 等级。

        复用 get_definitions_for_availability 获取 OpenAI 包装格式的 schema，
        然后按 danger_level 过滤为 safe。
        """
        all_defs: list[dict] = tool_registry.get_definitions_for_availability(
            ToolAvailability.TASKAGENT,
        )
        result: list[dict] = []
        for schema in all_defs:
            func: dict = schema.get("function") or {}
            name: str = func.get("name", "")
            entry = tool_registry.get_entry(name)
            if entry is not None and entry.danger_level == ToolDangerLevel.safe:
                result.append(schema)
        return result

    def _get_agent_loop(self) -> IMainSessionLoop | None:
        """解析当前父 session 对应的真实主会话 loop（SP-5 D6：移除 isinstance 门）。

        Orchestrator 在启动时拿到的是 __bootstrap__ loop，而每个真实 session
        都由 SessionManager 维护独立的 loop，因此需要动态解析。
        ParentAgentLoop 与 MultiAgentLoop 均持有 _message_queue，均可接收子 agent 反馈。
        """
        try:
            from system.application import Application
            sm = Application.current().session_manager
            if sm is not None:
                loop = sm.get_loop(self._parent_session_id)
                if loop is None:
                    return None
                return loop
        except Exception:
            logger.warning(
                "Failed to resolve real loop for parent=%s; falling back to bootstrap loop",
                self._parent_session_id,
                exc_info=True,
            )
        return self._agent_loop

    # ── SP-5 D4：事件驱动子→主投递 ──────────────────────────────────

    async def _subagent_waiter(self, session_id: str, sub: SubAgentLoop) -> None:
        """per-subagent 事件驱动 waiter：outbox/pending 变化时即时投递父队列。

        R1 修复：循环头 while True，body 内 flush 先于 break-check——
        taskagent 正常完成时 outbox.append→completed 之间无 await，waiter 唤醒
        时 completed=True，若 break-check 在 flush 之前则最终 outbox 永久丢失。
        """
        try:
            while True:
                await sub._outbox_event.wait()
                sub._outbox_event.clear()
                # 先 flush（drain outbox + pending → push 父队列）
                await self._flush_subagent_message(session_id, sub)
                # 后 break-check（独占出口判定）
                if self._shutting_down or sub.completed or sub.terminated:
                    # taskagent cleanup（原 _collect_and_inject 末尾逻辑）
                    if isinstance(sub, TaskAgentLoop) and sub.completed:
                        self._cleanup_taskagent(session_id)
                    self._waiter_tasks.pop(session_id, None)
                    break
        except asyncio.CancelledError:
            raise

    async def _flush_subagent_message(self, session_id: str, sub: SubAgentLoop) -> None:
        """收集单个子 Agent 的 outbox + pending 快照，格式化为 [subagent-result] 并 push 父队列。"""
        outbox = sub.get_outbox()
        pending = sub.pending_approvals_info
        if not outbox and not pending:
            return
        parts: list[str] = []
        parts.append(f"session_id: {session_id}")
        if outbox:
            merged = SUB_MESSAGE_SEPARATOR.join(outbox)
            parts.append(f"feedback:\n  {merged}")
        if pending:
            parts.append("pending_approvals:")
            for p in pending:
                parts.append(f"  - tool_call_id: {p['tool_call_id']}")
                parts.append(f"    tool_name: {p['tool_name']}")
                parts.append(f"    arguments: {json.dumps(p['arguments'], ensure_ascii=False)}")
        full_message = read_template("subagent/result_message.txt") + "\n\n" + "\n".join(parts)
        loop = self._get_agent_loop()
        if loop is None or loop.loop is None or loop.loop._message_queue is None:
            logger.warning("Cannot flush subagent message: parent queue unavailable | session=%s", session_id)
            return
        try:
            loop.loop._message_queue.push(
                full_message, character_name=SYSTEM_CHARACTER_NAME, source="subagent",
            )
            logger.debug("Subagent result pushed to parent queue | parent=%s session=%s", self._parent_session_id, session_id)
        except Exception as exc:
            logger.exception(
                "Failed to push subagent result for parent=%s session=%s: %s",
                self._parent_session_id, session_id, exc,
            )

    def _cleanup_taskagent(self, session_id: str) -> None:
        """清理已完成的 taskagent（原 _collect_and_inject 末尾逻辑）。"""
        self._active.pop(session_id, None)
        task = self._active_task.pop(session_id, None)
        if task and not task.done():
            task.cancel()
        self._subagent_names.pop(session_id, None)
        logger.info("Taskagent cleaned up | session=%s", session_id)

    @staticmethod
    def _history_path(session_id: str, name: str = "") -> Path:
        """子 Agent 会话历史的存储路径（easysave 多态序列化格式）。"""
        ctx = get_runtime_context()
        dir = ctx.agentspace / "subagents"
        if name:
            dir = dir / name
        dir.mkdir(parents=True, exist_ok=True)
        return dir / f"{session_id}.es"


class SubAgentOrchestrator:
    """按主会话管理多个子 Agent 上下文。"""

    def __init__(self) -> None:
        self._agent_loop: IMainSessionLoop | None = None
        self._contexts: dict[str, _OrchestratorContext] = {}

    def set_agent_loop(self, agent_loop: IMainSessionLoop) -> None:
        """注入父 AgentLoop 引用。"""
        self._agent_loop = agent_loop

    def _get_context(self, parent_session_id: str) -> _OrchestratorContext:
        """获取或创建指定父会话的上下文。"""
        if parent_session_id not in self._contexts:
            assert self._agent_loop is not None, "set_agent_loop() must be called before any context operation"
            ctx = _OrchestratorContext(parent_session_id, self._agent_loop)
            self._contexts[parent_session_id] = ctx
            # SP-5 D4：事件驱动 waiter 由 _start_subagent/_start_taskagent 启动，无需后台周期任务
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

    async def launch_taskagent(self, parent_session_id: str, prompt: str, temperature: float) -> dict[str, Any]:
        return await self._get_context(parent_session_id).launch_taskagent(parent_session_id, prompt, temperature)

    async def stop_taskagent(self, parent_session_id: str, session_id: str) -> dict[str, Any]:
        return await self._get_context(parent_session_id).stop_taskagent(session_id)

    def interrupt(self, parent_session_id: str) -> None:
        self._get_context(parent_session_id).interrupt()

    def resume(self, parent_session_id: str) -> None:
        self._get_context(parent_session_id).resume()

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

    async def shutdown(self, parent_session_id: str) -> None:
        """关闭指定父会话的所有子 Agent 并清理上下文。"""
        ctx = self._contexts.pop(parent_session_id, None)
        if ctx is not None:
            await ctx.shutdown()
