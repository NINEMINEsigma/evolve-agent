"""
MultiAgentLoop — 多 Agent 广播协作循环。

继承 BaseAgentLoop，管理共享 History + 多 Agent 串行级联调度。
自身不直接调用 LLM，而是将每个 Agent 的执行委托给 MultiAgentWorker。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from pathlib import Path
from typing import Any, TYPE_CHECKING

from abstract.llm.client import BaseLLMClient
from entity.messages import (
    History,
    CharacterConversationMessage,
)
from entity.puretype import Role, ToolAvailability, AgentConfig, LoopMeta, Loop
from entity.constant import (
    MAIN_AGENT_CHARACTER_NAME,
    USER_CHARACTER_NAME,
    MULTI_AGENT_MAX_CASCADE_DEPTH,
    LOG_PREVIEW_CHARS,
    INHERIT_LAST_ROUNDS,
)
from system.templates import get_templates_dir, render_multi_agent_prompt
from system.session_store import SessionStore
from entry.base_agent_loop import BaseAgentLoop, IMainSessionLoop
from entry.multi_agent_worker import WorkerResult, MultiAgentWorker
from entry.agent_support.multimodal import content_to_text, summarize_message_for_log

if TYPE_CHECKING:
    from system.application import Application
    from entry.agent_sink import AgentSink
    from entity.messages import ToolResultMessage

logger = logging.getLogger(__name__)

# 运行时加载的模板缓存
_Final_Round_Prompt: str | None = None


class AgentProfile:
    """单个 Agent 的运行时档案，持有可序列化配置 + 不可序列化的运行时资源。"""

    def __init__(
        self,
        character_name: str,
        system_prompts: list[str],
        tools: list[dict],
        llm_client: BaseLLMClient,
        config: AgentConfig,
    ) -> None:
        self.character_name: str = character_name
        self.system_prompts: list[str] = system_prompts
        self.tools: list[dict] = tools
        self.llm_client: BaseLLMClient = llm_client
        self.config: AgentConfig = config


class MultiAgentLoop(BaseAgentLoop, IMainSessionLoop):
    """多 Agent 广播协作循环。

    持有共享 History 实例，管理多 Agent 串行响应的调度和级联。
    每条消息通过 ``visible_characters`` 控制可见性，
    通过 ``response_characters`` 指定下一轮响应的 Agent。
    """

    def __init__(
        self,
        app: Application,
        session_id: str,
        *,
        history: History,
        agents: dict[str, AgentProfile],
        sink: AgentSink,
        history_store_dir: Path | None = None,
    ) -> None:
        super().__init__(app, session_id)
        self._history: History = history
        self._agents: dict[str, AgentProfile] = agents
        self._sink: AgentSink = sink
        self._agent_names: list[str] = list(agents.keys())
        self._session_store: SessionStore | None = (
            SessionStore(history_store_dir) if history_store_dir else None
        )

        # token 消耗统计：从磁盘恢复历史累计值，避免从普通模式切换后覆盖已有消耗
        self._token_usage: int = 0
        self._last_prompt_tokens: int = 0
        # 旋转通知：old_sid → new_sid（供 gateway 层 pop_session_rotated 读取）
        self._session_rotated_notify: dict[str, str] = {}
        if self._session_store is not None:
            try:
                self._token_usage = self._session_store.read_token_usage(session_id)
            except Exception as exc:
                logger.warning(
                    "Failed to load token usage for session %s: %s", session_id, exc
                )

        logger.info(
            "MultiAgentLoop initialized | session=%s agents=%d history_store=%s token_usage=%d",
            session_id, len(self._agent_names), bool(history_store_dir), self._token_usage,
        )

    # -- BaseAgentLoop 抽象方法实现 ----------------------------------------

    def get_sink(self) -> AgentSink:
        return self._sink

    @property
    def user_character_name(self) -> str:
        return USER_CHARACTER_NAME

    def get_agents(self) -> dict[str, AgentProfile]:
        """返回当前多 Agent loop 中的 agent 配置档案副本。"""
        return dict(self._agents)

    async def append_user_message(
        self, content: Any, *, display_content: Any | None = None,
        visible_characters: list[str] | None = None,
        response_characters: list[str] | None = None,
        client_message_id: str | None = None,
        **kwargs,
    ) -> int:
        """追加用户消息到 History 并回显到前端。"""
        _visible = visible_characters if visible_characters else self._agent_names
        hooks_context, fixator_context = self._collect_hooks_context()
        msg = CharacterConversationMessage(
            role=Role.USER,
            character_name=USER_CHARACTER_NAME,
            content=str(content),
            visible_characters=_visible,
            response_characters=response_characters,
            message_suffix=fixator_context or None,
            dynamic_message_suffix=hooks_context or None,
        )
        idx = self._history.add_message(msg)
        self.save_history(self.session_id)
        await self._sink.emit_user_message(
            self.session_id,
            display_content if display_content is not None else str(content),
            USER_CHARACTER_NAME,
            idx,
            visible_characters=_visible,
            response_characters=response_characters,
            client_message_id=client_message_id,
            message_suffix=fixator_context or None,
            dynamic_message_suffix=hooks_context or None,
        )
        logger.info(
            "Appended user message | session=%s index=%d content=%s",
            self.session_id, idx, summarize_message_for_log(content),
        )
        return idx

    # -- 公开接口 ----------------------------------------------------------

    # 上下文超限检测已在 MultiAgentWorker tool loop 内 per-agent 实现（见 _cascade 中的 context_over_limit 检查）。
    # 以下 _is_context_over_limit 仅为 process_message 级别的兜底检测。

    def _is_context_over_limit(self, safety_margin: int = 5000) -> bool:
        """检查最后一次 LLM 调用的 prompt_tokens 是否超过全局上下文上限。

        per-agent 的超限检测已在 Worker tool loop 内通过 max_context_tokens 完成，
        此方法作为兜底：当 Worker 使用全局 RuntimeContext 配置时（max_context_tokens=0），
        回退到全局上限检测。
        """
        if self._last_prompt_tokens == 0:
            return False
        ctx = self.app.runtime_context
        return (
            self._last_prompt_tokens + ctx.llm_max_output_tokens + safety_margin
        ) > ctx.llm_max_context_tokens

    async def _rotate_session_for_context_limit(self) -> str | None:
        """上下文超限时终结当前会话并创建继承会话（多 Agent 模式）。

        新会话继承原会话的 agents 列表，以多 Agent 模式重建。
        """
        from entry.session_manager import terminate_and_rotate_session

        old_sid = self.session_id
        loop_meta = LoopMeta(loopType=Loop.multi, agents=list(self._agents.keys()))

        # 确定历史存储目录
        history_store_dir = None
        if self._session_store is not None:
            history_store_dir = self._session_store.base_dir

        # 获取用于生成摘要的 LLM 客户端
        llm = self._get_session_info_llm_client()

        # 获取 gateway 层 SessionManager
        sm = self.session_manager
        if sm is None:
            logger.warning("Cannot rotate: session_manager is None | session=%s", old_sid)
            return None

        try:
            new_sid = await terminate_and_rotate_session(
                session_id=old_sid,
                session_store=self._session_store,
                session_manager=sm,
                llm=llm,
                loop_meta=loop_meta,
                current_character_agent=self.current_character_agent,
                history_store_dir=history_store_dir,
            )
        except Exception:
            logger.exception(
                "Failed to rotate session for context limit | session=%s", old_sid,
            )
            return None

        if new_sid:
            self.session_id = new_sid
            self._last_prompt_tokens = 0
            self._session_rotated_notify[old_sid] = new_sid
            logger.info(
                "Multi-agent session rotated for context limit | old=%s new=%s",
                old_sid, new_sid,
            )
        return new_sid

    def pop_session_rotated(self) -> str | None:
        """取出并移除旋转通知（old_sid → new_sid），供 gateway 层读取。"""
        return self._session_rotated_notify.pop(self.session_id, None)

    @property
    def current_character_agent(self) -> str:
        """返回当前 loop 的代表角色名。多 Agent 模式下返回首个 Agent。"""
        return self._agent_names[0] if self._agent_names else USER_CHARACTER_NAME

    def get_token_usage(self) -> int:
        """返回会话级累计总 token 消耗（含普通模式已累积部分）。"""
        return self._token_usage

    def get_context_tokens(self) -> int:
        """返回最近一次 LLM 调用的 prompt_tokens。

        多 Agent 模式下各 agent 的上下文不同，该值仅为最近一次 agent 调用的上下文快照，
        不代表整个多 Agent 会话的统一上下文占用。
        """
        return self._last_prompt_tokens

    # -- LLM 客户端 -------------------------------------------------------

    def _get_session_info_llm_client(self) -> BaseLLMClient | None:
        """返回用于生成标题/标签/摘要等会话信息的 LLM 客户端，首选主 Agent 配置。"""
        agent = self._agents.get(MAIN_AGENT_CHARACTER_NAME)
        if agent is None and self._agents:
            agent = next(iter(self._agents.values()))
        return agent.llm_client if agent else None

    def clear_session(self) -> None:
        """清空 History。"""
        self._history.clear_messages()
        logger.info("Cleared multi-agent session | session=%s", self.session_id)

    def get_tool_availability_scope(self) -> ToolAvailability:
        return ToolAvailability.MULTI_AGENT

    async def terminate_session(self) -> dict:
        """终结当前会话：中断级联 + 生成摘要 + 归档。"""
        logger.info("Terminating multi-agent session | session=%s", self.session_id)
        # 1. 中断级联，使 _cascade 在下一个 step 退出
        self.interrupt()
        # 2. 生成并持久化摘要（复用 BaseAgentLoop.regenerate_summary_for_session）
        if self._session_store is not None:
            try:
                await self.regenerate_summary_for_session(self.session_id)
            except Exception:
                logger.exception(
                    "Failed to generate summary for session=%s", self.session_id,
                )
        # 3. 归档（通过 gateway SessionManager）
        if self.session_manager is not None:
            try:
                self.session_manager.archive(self.session_id, continuation_sid=None)
            except Exception:
                logger.exception(
                    "Failed to archive session=%s", self.session_id,
                )
        return {"terminated": True, "session_id": self.session_id}

    async def merge_sessions(self, sources: list[str]) -> dict:
        """从源会话摘要创建继承会话，新会话降级为普通模式。

        多 agent 会话的摘要继承了多 agent 的对话历史，但新会话本身
        以普通模式（ParentAgentLoop）启动，用户可在此基础上继续对话。
        """
        if self.session_manager is None:
            return {"error": "session manager not available", "merged": False}
        if not sources:
            return {"error": "sources list is empty", "merged": False}
        if self._session_store is None:
            return {"error": "session store not available", "merged": False}

        from entry.agent_support.history_summary import (
            summarize_history, messages_to_text, extract_last_rounds,
        )
        from system.templates import read_template

        # 收集各源 session 的摘要，缺失时自动生成
        summaries: list[str] = []
        for sid in sources:
            summary = self._session_store.read_summary(sid)
            logger.info(
                "merge_sessions: source=%s summary_len=%d",
                sid, len(summary),
            )
            if not summary:
                history = self._session_store.read_history(sid)
                if history and history.count > 0:
                    llm = self._get_session_info_llm_client()
                    if llm is not None:
                        summary = await summarize_history(history, llm)
                    if summary:
                        self._session_store.write_summary(sid, summary)
            if summary:
                summaries.append(f"[Session {sid}]: {summary}")

        if not summaries:
            return {"error": "no summaries found for source sessions", "merged": False}

        # 构建初始上下文
        if len(summaries) == 1:
            context = (
                read_template("session_inherit.txt")
                .replace("{{old_sid}}", sources[0])
                .replace("{{summary}}", summaries[0])
            )
        else:
            # 多源合并：直接拼接，不截断
            joined = "\n\n---\n\n".join(summaries)
            context = (
                f"This session merges multiple previous sessions. "
                f"Here are their summaries:\n\n"
                f"{joined}"
            )

        # 创建新 session（降级为普通模式，不传 loop_meta）
        new_sid = self.session_manager.create_with_context(
            context=context,
            parent_sid=sources[0],
            parents=sources,
            role=Role.USER,
        )

        # 追加各源会话尾部轮次文本
        tail_blocks: list[str] = []
        for sid in sources:
            try:
                src_history = self._session_store.read_history(sid)
                if src_history is None or src_history.count == 0:
                    continue
                tail_msgs = extract_last_rounds(
                    src_history,
                    rounds=INHERIT_LAST_ROUNDS,
                    include_tool_messages=False,
                )
                if tail_msgs:
                    tail_blocks.append(
                        f"### Source session {sid}\n" + messages_to_text(tail_msgs)
                    )
            except Exception:
                logger.exception("Failed to append tail rounds for source=%s", sid)
        if tail_blocks:
            context += "\n\n## Recent conversation rounds\n" + "\n\n---\n\n".join(tail_blocks)

        # 写入仅含 summary 消息的历史
        summary_history = History()
        summary_history.add_message(CharacterConversationMessage(
            role=Role.USER,
            character_name=USER_CHARACTER_NAME,
            content=context,
            visible_characters=[self.current_character_agent],
        ))
        self._session_store.write_history(new_sid, summary_history)

        # 归档源 sessions
        for sid in sources:
            self.session_manager.archive(sid, continuation_sid=new_sid)

        logger.info(
            "Multi-agent sessions merged | new=%s sources=%s summaries=%d",
            new_sid, sources, len(summaries),
        )
        return {"merged": True, "session_id": new_sid, "sources": sources}

    async def process_message(
        self,
        user_message: str,
        *,
        skip_append: bool = False,
        character_name: str = USER_CHARACTER_NAME,
        visible_characters: list[str] | None = None,
        response_characters: list[str] | None = None,
        **kwargs,
    ) -> str:
        """处理用户消息入口。

        每轮用户消息触发一次级联对话：
        1. 追加用户消息到 History（skip_append 为 True 时跳过）
        2. 以指定的 response_characters 为初始响应者启动级联
           - 若为 None，默认所有 Agent 响应
        3. 各 Agent 回复已通过 sink 独立推送前端，本方法返回空字符串

        visible_characters / response_characters 由用户从前端指定；
        未指定时默认对全体可见、全体响应。
        """
        # 新消息到达时重置中断状态，允许用户从停止状态恢复
        self._cancel_event.clear()
        if self.is_interrupted():
            logger.warning("process_message skipped: loop interrupted | session=%s", self.session_id)
            return ""

        # 用户消息的可见角色 — "all-agents" 简写展开
        _visible = visible_characters if visible_characters else self._agent_names
        from entity.constant import ALL_AGENTS_CHARACTER_REF_NAME
        if _visible == [ALL_AGENTS_CHARACTER_REF_NAME]:
            _visible = self._agent_names
        # 初始响应角色
        _response = response_characters if response_characters else self._agent_names
        if _response == [ALL_AGENTS_CHARACTER_REF_NAME]:
            _response = self._agent_names

        logger.info(
            "Received user message | session=%s content=%s visible=%s response=%s",
            self.session_id, summarize_message_for_log(user_message), _visible, _response,
        )

        # 追加用户消息
        if not skip_append:
            await self.append_user_message(
                user_message,
                visible_characters=_visible,
                response_characters=_response,
            )
            logger.info(
                "Appended user message to history | session=%s visible=%s",
                self.session_id, _visible,
            )

        # 以用户指定的角色（或全体）作为初始响应者
        await self._cascade(_response)

        # 超限检测触发后旋转会话
        if self._last_prompt_tokens > 0 and self._is_context_over_limit():
            logger.warning(
                "Context limit reached after cascade, rotating | session=%s",
                self.session_id,
            )
            await self._rotate_session_for_context_limit()

        # 收集本轮所有 Agent 的回复（用户消息之后的消息）
        responses: list[str] = []
        for msg in self._history.iter_messages():
            if isinstance(msg, CharacterConversationMessage) and msg.role == Role.ASSISTANT:
                if msg.character_name in self._agents:
                    text = msg.content if isinstance(msg.content, str) else str(msg.content)
                    responses.append(f"[{msg.character_name}]: {text}")

        logger.info(
            "Cascade completed | session=%s responses=%d",
            self.session_id, len(responses),
        )

        # 每个 agent 已通过 emit_stream_delta + emit_stream_done 独立推送到前端，
        # 不再需要在此返回拼接文本给 gateway 用于 assistant_message。
        return ""

    # -- 级联调度 ----------------------------------------------------------

    def _get_available_subagents(self, characters: list[str]) -> list[str]:
        """从 SubagentStore 过滤出还有 profile 的 agent。

        若某个 agent 的 subagent profile 已被其他会话删除，则将其从
        response_characters 中移除，后续不再接受其响应。历史消息不受影响。
        """
        from component.mutliagenttools._store import SubagentStore
        from system.context import get_runtime_context
        store = SubagentStore(get_runtime_context().agentspace)
        available = [c for c in characters if store.get(c) is not None]
        dropped = set(characters) - set(available)
        if dropped and MAIN_AGENT_CHARACTER_NAME in dropped:
            dropped.remove(MAIN_AGENT_CHARACTER_NAME)
        if dropped:
            logger.warning(
                "Subagent profiles dropped: %s; removing from response_characters (session=%s)",
                dropped, self.session_id,
            )
        return available

    async def _cascade(
        self,
        response_characters: list[str],
    ) -> None:
        """串行动态队列级联调度。

        按原始 response_characters 顺序初始化动态队列，严格串行执行：
        每步弹出一个 Agent，**等待其完全完成（含 tool loop 和 History 写入）**后，
        再启动下一个。Agent 响应中指定的 response_characters 会动态调整队列：
        - 已在队列中：移到队首（优先执行）
        - 不在队列中：加到队尾
        - 自我指定：忽略

        最大深度按步数计算：len(agents) * MULTI_AGENT_MAX_CASCADE_DEPTH。
        剩余步数 ≤ 3 时注入 final-round 提示词强制收敛。
        Agent 响应正常时继续处理队列中下一个；仅当代码异常时中断队列并发送系统消息报错。

        发起者自动回调：当 Agent A 指定 B/C 响应后，A 的 pending 集合记录 {B, C}。
        每个 agent 完成时从所有 pending 中移除自身；当某发起者的 pending 清空时，
        该发起者自动入队（移到队首），每个 agent 每次级联最多自动回调 1 次。
        显式指定的 response_characters 不受回调次数限制。
        """
        # ── 构建初始队列 ──
        is_contains_main_agent = MAIN_AGENT_CHARACTER_NAME in response_characters
        filtered = self._get_available_subagents(response_characters)
        if is_contains_main_agent:
            filtered.append(MAIN_AGENT_CHARACTER_NAME)

        # 过滤不存在的 Agent 名
        valid_chars = [c for c in filtered if c in self._agents]
        invalid_chars = set(filtered) - set(valid_chars)
        if invalid_chars:
            logger.warning(
                "Ignoring unknown response_characters: %s", invalid_chars
            )

        if not valid_chars:
            return

        queue: deque[str] = deque(valid_chars)
        step: int = 0
        max_steps: int = len(self._agents) * MULTI_AGENT_MAX_CASCADE_DEPTH

        # 发起者 pending 跟踪：initiator -> {待响应的 agent 名集合}
        pending_map: dict[str, set[str]] = {}
        # 发起者已自动回调次数：initiator -> 0 或 1
        callback_count: dict[str, int] = {}

        logger.info(
            "Cascade start (serial) | session=%s queue=%s max_steps=%d",
            self.session_id, list(queue), max_steps,
        )

        while queue and step < max_steps:
            char = queue.popleft()

            # 中断检查：用户请求停止时立即退出级联
            if self.is_interrupted():
                logger.info(
                    "Cascade interrupted by user | session=%s step=%d character=%s",
                    self.session_id, step, char,
                )
                return

            # 跳过无效 Agent
            if char not in self._agents:
                continue

            is_final = (max_steps - step) <= 3

            logger.info(
                "Cascade step | session=%s step=%d/%d character=%s final=%s queue=%s",
                self.session_id, step, max_steps, char, is_final, list(queue),
            )

            # ── 执行单个 Agent ──
            try:
                result = await self._run_single_agent(char, is_final_round=is_final)
            except Exception as exc:
                logger.exception(
                    "Agent worker failed, cascade interrupted | session=%s character=%s step=%d",
                    self.session_id, char, step,
                )
                await self._sink.emit_system_message(
                    self.session_id,
                    json.dumps({
                        "cascade_error": True,
                        "agent": char,
                        "step": step,
                        "error": f"{type(exc).__name__}: {exc}",
                    }, ensure_ascii=False),
                )
                return

            # ── 超限检查：任一 Agent 超限则立即中断级联 ──
            if result.context_over_limit:
                logger.warning(
                    "Context over limit detected, cascade interrupted | "
                    "session=%s character=%s step=%d",
                    self.session_id, char, step,
                )
                break

            # ── 中断检查：loop 被替换（如 exit_multi_agent）后立即退出 ──
            if self.is_interrupted():
                logger.info(
                    "Cascade interrupted after agent run, skipping history write | "
                    "session=%s character=%s step=%d",
                    self.session_id, char, step,
                )
                return

            # ── 解析结果并写入 History ──
            parsed = result.parsed_json
            content_text = parsed.content

            visible = parsed.visible_characters if parsed.visible_characters else list(self._agent_names)

            # 最后一轮：强制忽略 response_characters
            response = list(parsed.response_characters) if not is_final else []

            preview = content_text[:LOG_PREVIEW_CHARS] + "..." if len(content_text) > LOG_PREVIEW_CHARS else content_text
            logger.info(
                "Agent response | session=%s character=%s step=%d content=%s visible=%s response=%s",
                self.session_id, result.character_name, step, preview,
                visible, response,
            )

            msg = CharacterConversationMessage(
                role=Role.ASSISTANT,
                character_name=result.character_name,
                content=str(content_text),
                visible_characters=visible if visible else None,
                response_characters=response if response else None,
                reasoning=result.parsed_json.reasoning,
                tool_calls=None,
                message_suffix=None,
            )

            self._history.add_message(msg)
            self.save_history(self.session_id)

            # 推送可见性/响应元数据给前端
            # 注意：MultiAgentWorker 已经在每轮 LLM 调用后发送过 stream_done，
            # 此处只需发送 system_message 关联元数据，避免重复固化。
            if result.stream_id and (visible or response):
                try:
                    await self._sink.emit_system_message(
                        self.session_id,
                        json.dumps({
                            "stream_meta": {
                                "stream_id": result.stream_id,
                                "visible_characters": visible,
                                "response_characters": response,
                            },
                        }, ensure_ascii=False),
                    )
                except Exception:
                    logger.debug("Failed to push visibility metadata for stream=%s", result.stream_id, exc_info=True)

            # ── 动态调整队列 + 发起者 pending 回调 ──
            if not is_final:
                # 1. 登记发起者的 pending（仅当 response 非空时）
                if response:
                    valid_targets = {rc for rc in response if rc in self._agents and rc != char}
                    if valid_targets:
                        pending_map[char] = valid_targets
                        callback_count.setdefault(char, 0)

                # 2. 显式 response_characters 入队逻辑（不变）
                for rc in response:
                    # 过滤：仅保留有效 Agent，排除自我指定
                    if rc not in self._agents or rc == char:
                        continue
                    if rc in queue:
                        # 已在队列中：移到队首
                        queue.remove(rc)
                        queue.appendleft(rc)
                        logger.info(
                            "Queue reorder: %s moved to front | session=%s step=%d",
                            rc, self.session_id, step,
                        )
                    else:
                        # 不在队列中：加到队尾
                        queue.append(rc)
                        logger.info(
                            "Queue append: %s added to back | session=%s step=%d",
                            rc, self.session_id, step,
                        )

                # 3. 当前完成的 agent 从所有 pending 中移除，检查回调触发
                for initiator, pending in list(pending_map.items()):
                    pending.discard(char)
                    if not pending and callback_count.get(initiator, 0) == 0:
                        # pending 清空且该 initiator 尚未回调过
                        if initiator in queue:
                            queue.remove(initiator)
                        queue.appendleft(initiator)
                        callback_count[initiator] = 1
                        logger.info(
                            "Callback enqueue: %s (pending cleared) | session=%s step=%d",
                            initiator, self.session_id, step,
                        )

            step += 1

        if step >= max_steps:
            logger.warning(
                "Cascade step limit (%d) reached for session=%s",
                max_steps, self.session_id,
            )

        logger.info(
            "Cascade completed (serial) | session=%s steps=%d",
            self.session_id, step,
        )

    # -- 单 Agent 执行 -----------------------------------------------------

    async def _run_single_agent(
        self, character_name: str, *, is_final_round: bool = False
    ) -> WorkerResult:
        """启动单个 Agent 的 tool loop + JSON 输出。

        委托给 MultiAgentWorker 执行完整的 LLM → tool_calls → tool_result → 循环。
        """
        profile = self._agents[character_name]

        # 构建该 Agent 视角的 History 视图；
        # dynamic_message_suffix 已在 append_user_message 中设置，由 History 自动附加。
        history_view = self._history.get_messages(
            current_character_agent=character_name,
            )

        logger.info(
            "Agent worker start | session=%s character=%s history_len=%d final=%s",
            self.session_id, character_name, len(history_view), is_final_round,
        )

        # 最后一轮：追加 final-round 提示词
        system_prompts = profile.system_prompts
        logger.info(
            "Agent worker system prompts | session=%s character=%s is_final=%s prompt_count=%d total_len=%d",
            self.session_id, character_name, is_final_round, len(system_prompts), sum(len(p) for p in system_prompts),
        )
        if is_final_round:
            global _Final_Round_Prompt
            if _Final_Round_Prompt is None:
                template_path = get_templates_dir() / "multiagent" / "multi_agent_final_round_prompt.txt"
                with open(template_path, "r", encoding="utf-8") as f:
                    _Final_Round_Prompt = render_multi_agent_prompt(f.read(), character_name)
            system_prompts = system_prompts + [_Final_Round_Prompt]
            logger.info(
                "Agent worker final round prompt appended | session=%s character=%s new_prompt_count=%d",
                self.session_id, character_name, len(system_prompts),
            )

        worker = MultiAgentWorker(
            character_name=character_name,
            system_prompts=system_prompts,
            history=history_view,
            tools=profile.tools,
            llm_client=profile.llm_client,
            sink=self._sink,
            loop=self,
            max_context_tokens=profile.config.max_context_tokens,
            max_output_tokens=profile.config.max_output_tokens,
        )

        try:
            result = await worker.run()
        except Exception:
            logger.exception(
                "Agent worker run failed | session=%s character=%s final=%s",
                self.session_id, character_name, is_final_round,
            )
            # 即使 worker 异常，也要把已累加的 token 消耗同步回 loop，避免部分消耗丢失
            self._aggregate_worker_usage(worker)
            raise

        self._aggregate_worker_usage(worker, result)

        logger.info(
            "Agent worker done | session=%s character=%s token_usage=%d",
            self.session_id, character_name, self._token_usage,
        )
        return result

    def _aggregate_worker_usage(
        self,
        worker: MultiAgentWorker,
        result: WorkerResult | None = None,
    ) -> None:
        """将 worker 的 token 消耗聚合到 loop 级累计值，并持久化、推送前端。"""
        total_token_usage = result.total_token_usage if result is not None else worker.total_token_usage
        last_prompt_tokens = result.last_prompt_tokens if result is not None else worker.last_prompt_tokens

        if total_token_usage:
            self._token_usage += total_token_usage
            self._last_prompt_tokens = last_prompt_tokens
            self._persist_token_usage(self.session_id)
            # 异步推送在前端展示；_push_usage_update 内部捕获异常，不会阻塞级联
            try:
                asyncio.get_running_loop().create_task(
                    self._push_usage_update(self.session_id)
                )
            except RuntimeError:
                # 无运行事件循环时（如同步测试场景），忽略推送
                pass
