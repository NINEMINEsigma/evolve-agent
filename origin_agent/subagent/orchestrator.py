"""子 Agent 编排器 — 进程级单例，管理所有子 Agent 的生命周期。

职责：
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
    SUBAGENT_READONLY_WHITELIST,
)
from abstract.tools.registry import registry as tool_registry
from system.context import get_runtime_context

from .context import SubRuntimeContext, build_subagent_context
from .loop import SUB_MESSAGE_SEPARATOR, SubAgentLoop, current_subagent_loop, format_user_message

logger = logging.getLogger(__name__)

# 全局编排器单例
_orchestrator: SubAgentOrchestrator | None = None


def get_orchestrator() -> SubAgentOrchestrator:
    if _orchestrator is None:
        raise RuntimeError("SubAgentOrchestrator not initialized")
    return _orchestrator


def set_orchestrator(o: SubAgentOrchestrator) -> None:
    global _orchestrator
    _orchestrator = o


class WaitingEntry:
    """等待队列条目。"""

    def __init__(
        self,
        session_id: str,
        profile: dict[str, Any],
        temperature: float,
        authorized_tools: list[str],
        initial_prompt: str,
        user_name: str,
        message_type: str,
        history_path: str = "",
    ) -> None:
        self.session_id: str = session_id
        self.profile: dict[str, Any] = profile
        self.temperature: float = temperature
        self.authorized_tools: list[str] = authorized_tools
        self.initial_prompt: str = initial_prompt
        self.user_name: str = user_name
        self.message_type: str = message_type
        self.history_path: str = history_path


class SubAgentOrchestrator:
    """子 Agent 编排器单例。

    由 gateway/server.py 初始化，工具层通过 get_orchestrator() 访问。
    """

    def __init__(self) -> None:
        self._active: dict[str, SubAgentLoop] = {}
        self._active_task: dict[str, asyncio.Task] = {}
        self._waiting_queue: deque[WaitingEntry] = deque()
        self._agent_loop: Any = None  # 父 AgentLoop 引用
        self._parent_session_id: str = ""
        self._background_task: asyncio.Task | None = None
        self._interrupted: bool = False
        self._shutting_down: bool = False
        self._subagent_names: dict[str, str] = {}  # session_id -> registry_name

    # ── 注入 ────────────────────────────────────────────────────────

    def set_agent_loop(self, agent_loop: Any, parent_session_id: str = "") -> None:
        """注入父 AgentLoop 引用并启动后台周期任务。"""
        self._agent_loop = agent_loop
        self._parent_session_id = parent_session_id
        if self._background_task is None:
            self._background_task = asyncio.create_task(
                self._cycle_loop(), name="subagent-cycle"
            )

    # ── 启动 ────────────────────────────────────────────────────────

    async def launch(
        self,
        profile: dict[str, Any],
        temperature: float,
        authorized_tools: list[str],
        initial_prompt: str,
        user_name: str,
        message_type: str,
        parent_session_id: str,
        history_path: str | None = None,
    ) -> dict[str, Any]:
        """启动一个子 Agent 会话。

        Args:
            history_path: 可选，之前 stop_subagent 保存的 JSONL 文件路径。
                          传入后子 Agent 在已有历史基础上继续。

        Returns:
            {success, session_id, waiting, queue_position}
        """
        # 动态更新父会话 ID（首次启动时记录）
        if not self._parent_session_id and parent_session_id:
            self._parent_session_id = parent_session_id

        session_id = f"{parent_session_id}_{uuid.uuid4().hex[:12]}"

        # 检查上限
        if len(self._active) >= SUBAGENT_MAX_ACTIVE:
            # 进入等待队列
            self._waiting_queue.append(
                WaitingEntry(
                    session_id=session_id,
                    profile=profile,
                    temperature=temperature,
                    authorized_tools=authorized_tools,
                    initial_prompt=initial_prompt,
                    user_name=user_name,
                    message_type=message_type,
                    history_path=history_path or "",
                )
            )
            logger.info(
                "Subagent queued | session=%s position=%d",
                session_id, len(self._waiting_queue),
            )
            return {
                "success": True,
                "session_id": session_id,
                "waiting": True,
                "queue_position": len(self._waiting_queue),
            }

        # 立即启动
        await self._start_subagent(
            session_id, profile, temperature, authorized_tools,
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

    async def chat(
        self,
        session_id: str,
        message: str,
        user_name: str,
        message_type: str,
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
        sub.inject_parent_message(message, user_name, message_type)
        # 推送父→子消息到前端子会话面板
        wrapped = format_user_message(user_name, message_type, message)
        await self._push_subagent_ws(
            session_id,
            self._subagent_names.get(session_id, ""),
            {"role": "user", "content": wrapped},
        )
        # 顺手收集一次 outbox，让父 Agent 获得即时反馈
        outbox = self._drain_outbox(sub)
        return {
            "success": True,
            "session_id": session_id,
            "feedback": outbox if outbox else None,
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
        """停止子 Agent 会话。

        Returns:
            {success, session_id, session_path, promoted, error}
        """
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

        # 推送 terminated 状态到前端面板，使该子会话从「运行中」变为「已终止」
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
        logger.info("Parent terminated: stopping all subagents")
        for session_id in list(self._active.keys()):
            await self.stop(session_id)
        self._waiting_queue.clear()

    def get_snapshot(self) -> dict[str, dict[str, Any]]:
        """返回所有活跃子会话的快照（供前端刷新时拉取）。"""
        snap: dict[str, dict[str, Any]] = {}
        for session_id, sub in self._active.items():
            feedback: list[dict[str, Any]] = []
            for entry in sub._history:
                role = str(entry.get("role", ""))
                if role == "system":
                    continue  # system prompt 不展示
                if role == "user":
                    feedback.append({"role": "user", "content": str(entry.get("content", ""))})
                elif role == "assistant":
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
                elif role == "tool":
                    feedback.append({
                        "role": "tool_result",
                        "tool_call_id": str(entry.get("tool_call_id", "")),
                        "content": str(entry.get("content", "")),
                    })
            status = "completed" if sub.completed else ("terminated" if sub.terminated else "running")
            snap[session_id] = {
                "name": self._subagent_names.get(session_id, ""),
                "status": status,
                "feedback": feedback,
                "pending_approvals": sub.pending_approvals_info,
            }
        return snap

    async def shutdown(self) -> None:
        """程序关闭时优雅停止所有活跃子 Agent。"""
        self._shutting_down = True
        if self._background_task and not self._background_task.done():
            self._background_task.cancel()
        logger.info("SubAgentOrchestrator shutdown: stopping %d active subagents", len(self._active))
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
        """推送一条结构化事件到前端面板。

        ``event`` 字段：role + 可选 content/tool_name/tool_call_id/tool_args/reasoning。
        ``role`` 取值：user / assistant / reasoning / tool_call / tool_result /
        approval_pending / approval_decision / status / countdown / completed / terminated。
        """
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
            await push_subagent_update(
                parent_session_id=self._parent_session_id,
                subagent_session_id=session_id,
                subagent_name=name,
                status=status,
                feedback=feedback,
                pending_approvals=pending,
            )
        except Exception as exc:
            logger.debug("WS push for subagent %s failed: %s", session_id, exc)

    async def _start_subagent(
        self,
        session_id: str,
        profile: dict[str, Any],
        temperature: float,
        authorized_tools: list[str],
        initial_prompt: str,
        user_name: str,
        message_type: str,
        history_path: str | None = None,
    ) -> None:
        """创建 SubAgentLoop 并以 asyncio.Task 启动。"""
        # 构建上下文
        parent_ctx = get_runtime_context()
        ctx = await build_subagent_context(profile, temperature, parent_ctx.workspace)

        # 构建工具集
        tools = self._build_tool_set(authorized_tools)

        # WS 推送回调 — loop 的每个事件即时推送给前端面板
        def _push_msg(event: dict[str, Any]) -> None:
            asyncio.create_task(self._push_subagent_ws(
                session_id, profile.get("_name", ""), event,
            ))

        # 创建并存储
        loop = SubAgentLoop(ctx, session_id, tools, MAX_TOOL_TURNS, on_message=_push_msg)
        self._active[session_id] = loop
        self._subagent_names[session_id] = profile.get("_name", "")

        # 若有历史文件，加载并预填到 loop._history（子 Agent 在已有上下文上继续）
        if history_path:
            hist_file = Path(history_path)
            if hist_file.exists():
                try:
                    with open(hist_file, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                entry = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            role = str(entry.get("role", ""))
                            # 跳过 system prompt（由本次启动重新注入）
                            if role == "system":
                                continue
                            loop._history.append(entry)
                            # 推送到前端面板
                            if role == "user":
                                await self._push_subagent_ws(
                                    session_id, profile.get("_name", ""),
                                    {"role": "user", "content": str(entry.get("content", ""))},
                                )
                            elif role == "assistant":
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
                            elif role == "tool":
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
                except Exception as exc:
                    logger.warning("Failed to load subagent history: %s", exc)

        # 立即推送 WS 通知前端面板
        await self._push_subagent_ws(
            session_id,
            profile.get("_name", ""),
            {"role": "status", "content": "started"},
            status_override="running",
        )

        # 推送 initial_prompt 到前端面板，确保刷新时不丢失
        wrapped_initial = format_user_message(user_name, message_type, initial_prompt)
        await self._push_subagent_ws(
            session_id,
            profile.get("_name", ""),
            {"role": "user", "content": wrapped_initial},
        )

        task = asyncio.create_task(loop.run(initial_prompt, user_name, message_type), name=f"subagent-{session_id[:16]}")
        self._active_task[session_id] = task

        logger.info(
            "Subagent started | session=%s model=%s tools=%d",
            session_id, ctx.model, len(tools),
        )

    async def _activate_next(self) -> list[dict[str, str]]:
        """从等待队列取出一个启动。返回被激活的会话信息列表。"""
        if not self._waiting_queue:
            return []
        entry = self._waiting_queue.popleft()
        await self._start_subagent(
            entry.session_id,
            entry.profile,
            entry.temperature,
            entry.authorized_tools,
            entry.initial_prompt,
            entry.user_name,
            entry.message_type,
            entry.history_path or None,
        )
        logger.info("Subagent activated from queue | session=%s", entry.session_id)
        return [{"session_id": entry.session_id, "subagent_name": entry.profile.get("name", "")}]

    def _build_tool_set(self, authorized_tools: list[str]) -> list[dict[str, Any]]:
        """构建子 Agent 的工具集。

        1. 从 SUBAGENT_READONLY_WHITELIST 获取 readonly 工具
        2. 追加 authorized_tools 中的 write/dangerous 工具
        3. 排除 multiagent 工具集
        """
        tool_names: set[str] = set()

        # 白名单
        for name in SUBAGENT_READONLY_WHITELIST:
            entry = tool_registry.get_entry(name)
            if entry is not None and entry.toolset != "multiagent":
                tool_names.add(name)

        # authorized_tools（已在前端校验为非 readonly、非 multiagent）
        for name in authorized_tools:
            entry = tool_registry.get_entry(name)
            if entry is not None and entry.toolset != "multiagent":
                tool_names.add(name)

        return tool_registry.get_definitions(tool_names=tool_names)

    async def _cycle_loop(self) -> None:
        """后台周期定时器 — 收集子 Agent 结果并注入父 Agent。"""
        while not self._shutting_down:
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                return

            if self._interrupted or self._shutting_down:
                continue

            # 检查父 Agent 是否空闲
            if self._agent_loop is None:
                continue
            if not hasattr(self._agent_loop, "_last_idle_time"):
                continue

            idle_sec = _time_module.monotonic() - self._agent_loop._last_idle_time

            # 每轮推送倒计时到前端（有活跃子 Agent 时）
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

            # 检查是否有父 Agent 正在处理消息
            if getattr(self._agent_loop, "_processing_sessions", None):
                processing = any(self._agent_loop._processing_sessions.values())
                if processing:
                    continue

            # 收集
            await self._collect_and_inject()

    async def _collect_and_inject(self) -> None:
        """收集所有活跃子 Agent 的 outbox 和待审批队列，注入父 Agent 并推送前端。"""
        messages: list[str] = []

        for session_id, sub in list(self._active.items()):
            parts: list[str] = []
            parts.append(f"session_id: {session_id}")

            # outbox
            outbox = sub.outbox
            sub._outbox.clear()
            if outbox:
                merged = SUB_MESSAGE_SEPARATOR.join(outbox)
                parts.append(f"feedback:\n  {merged}")

            # 待审批
            pending = sub.pending_approvals_info
            if pending:
                parts.append("pending_approvals:")
                for p in pending:
                    parts.append(f"  - tool_call_id: {p['tool_call_id']}")
                    parts.append(f"    tool_name: {p['tool_name']}")
                    parts.append(f"    arguments: {json.dumps(p['arguments'], ensure_ascii=False)}")

            if len(parts) > 1:  # 有 session_id 以外的内容
                messages.append("\n".join(parts))

            # 推送 WS 到前端（SubagentDrawer）— 仅同步状态与 pending_approvals。
            # assistant 文本已在 LLM 响应时通过 _push_subagent_ws 即时推送过，
            # 此处不要再用 list(outbox) 重复推送（会出现没有 role 的 MSG 空气泡）。
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

        # 空周期跳过
        if not messages:
            return

        # 构建 [subagent-result] 消息
        # 告知父 Agent：子 Agent 的消息是发给它的，不是发给最终用户的。
        # 用户看不到子会话面板里的内容，父 Agent 需要主动处理、回复或转达。
        full_message = (
            "[subagent-result]\n"
            "This is a sub-agent feedback message visible only to you (the parent agent); "
            "the end user does not directly see it. "
            "The sub-agent's 'user' is you — it sends feedback, asks questions, "
            "and requests tool approvals through you. "
            "You decide how to respond: approve/reject tools, send chat messages, "
            "or stop the sub-agent when its task is complete.\n\n"
        ) + "\n\n".join(messages)

        # 注入父 Agent（与 cron 相同的串行化机制）
        try:
            await self._agent_loop.process_message(
                self._parent_session_id, full_message
            )
            logger.debug("Subagent result injected to parent | entries=%d", len(messages))
        except Exception as exc:
            logger.warning("Failed to inject subagent result: %s", exc)

    @staticmethod
    def _history_path(session_id: str, name: str = "") -> Path:
        """子 Agent 会话历史的存储路径。

        文件名包含注册名（如果有），便于父 Agent 识别和管理。
        """
        ctx = get_runtime_context()
        dir = ctx.agentspace / "subagents"
        if name:
            dir = dir / name
        dir.mkdir(parents=True, exist_ok=True)
        return dir / f"{session_id}.jsonl"