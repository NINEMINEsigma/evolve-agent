"""
MultiAgentLoop — 多 Agent 广播协作循环。

继承 BaseAgentLoop，管理共享 History + 多 Agent 并发调度 + 级联递归。
自身不直接调用 LLM，而是将每个 Agent 的执行委托给 MultiAgentWorker。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, TYPE_CHECKING

from entity.messages import (
    History,
    CharacterConversationMessage,
    MessageBlock,
)
from entity.puretype import Role
from entity.constant import (
    MAIN_AGENT_CHARACTER_NAME,
    USER_CHARACTER_NAME,
    MULTI_AGENT_MAX_CASCADE_DEPTH,
)
from system.templates import get_templates_dir
from entry.base_agent_loop import BaseAgentLoop
from entry.multi_agent_worker import WorkerResult, MultiAgentWorker

if TYPE_CHECKING:
    from system.application import Application
    from entry.agent_sink import AgentSink

logger = logging.getLogger(__name__)

# 运行时加载的模板缓存
_Final_Round_Prompt: str | None = None


class AgentProfile:
    """单个 Agent 的配置档案。"""

    def __init__(
        self,
        character_name: str,
        system_prompt: str,
        tools: list[dict],
        llm_client: Any,
    ) -> None:
        self.character_name: str = character_name
        # TODO: 必须改成多条, 为了支持主agent和子agent的复杂提示词, 实际上并不能被合并
        self.system_prompt: str = system_prompt
        self.tools: list[dict] = tools
        self.llm_client: Any = llm_client


class MultiAgentLoop(BaseAgentLoop):
    """多 Agent 广播协作循环。

    持有共享 History 实例，管理多 Agent 并发响应的调度和级联。
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
    ) -> None:
        super().__init__(app, session_id)
        self._history: History = history
        self._agents: dict[str, AgentProfile] = agents
        self._sink: AgentSink = sink
        self._agent_names: list[str] = list(agents.keys())

    # -- BaseAgentLoop 抽象方法实现 ----------------------------------------

    def _get_sink(self) -> AgentSink:
        return self._sink

    @property
    def user_character_name(self) -> str:
        return USER_CHARACTER_NAME

    async def append_user_message(
        self, content: Any, *, display_content: Any | None = None
    ) -> int:
        """追加用户消息到 History。"""
        msg = CharacterConversationMessage.from_text(
            role=Role.USER,
            character_name=USER_CHARACTER_NAME,
            text=str(content),
            visible_characters=self._agent_names,
        )
        return self._history.add_message(msg)

    # -- 公开接口 ----------------------------------------------------------

    # TODO: 多agent模式下每个agent的上下文其实都不一样, 
    # 当第一个到达的时候就可以触发会话压缩和会话旋转了
    # TODO: 上下文超限检测和会话旋转（multi loop 当前不触发旋转）

    @property
    def current_character_agent(self) -> str:
        """返回当前 loop 的代表角色名。多 Agent 模式下返回首个 Agent。"""
        return self._agent_names[0] if self._agent_names else USER_CHARACTER_NAME

    def pop_session_rotated(self) -> str | None:
        """多 Agent 模式下不支持会话旋转，始终返回 None。"""
        return None

    def get_token_usage(self) -> int:
        """多 Agent 模式暂不支持 token 统计。"""
        return 0

    def get_context_tokens(self) -> int:
        """多 Agent 模式暂不支持上下文 token 统计。"""
        return 0

    def is_processing(self) -> bool:
        """多 Agent 模式下始终返回 False（无长时间 tool loop）。"""
        return False

    def get_session_messages(self) -> list[dict]:
        """返回 History 中所有消息的字典列表（供前端展示）。"""
        result: list[dict] = []
        for msg in self._history.messages:
            entry: dict = {
                "role": msg.role.value,
                "content": str(msg.content) if not isinstance(msg.content, list) else "",
            }
            if hasattr(msg, "character_name"):
                entry["character_name"] = getattr(msg, "character_name")
            if hasattr(msg, "visible_characters") and getattr(msg, "visible_characters"):
                entry["visible_characters"] = getattr(msg, "visible_characters")
            result.append(entry)
        return result

    def clear_session(self) -> None:
        """清空 History。"""
        self._history.messages.clear()

    def delete_session_messages(self, count: int = 1) -> dict:
        """删除最近 N 条消息。"""
        removed = min(count, len(self._history.messages))
        for _ in range(removed):
            self._history.messages.pop()
        return {"deleted": removed, "session_id": self.session_id, "remaining_count": len(self._history.messages)}

    def get_tool_resources(self) -> dict:
        """多 Agent 模式暂不支持工具资源恢复。"""
        # TODO: 需要补充
        return {"task_progress": {}, "clipboard_display": {}}

    async def terminate_session(self) -> dict:
        """终结当前会话。"""
        return {"terminated": True, "session_id": self.session_id}

    async def merge_sessions(self, sources: list[str]) -> dict:
        """多 Agent 模式暂不支持会话合并。"""
        # TODO: 需要补充
        return {"error": "merge not supported in multi-agent mode", "merged": False}

    async def process_message(
        self,
        user_message: str,
        *,
        skip_append: bool = False,
        character_name: str = USER_CHARACTER_NAME,
        visible_characters: list[str] | None = None,
        response_characters: list[str] | None = None,
    ) -> str:
        """处理用户消息入口。

        每轮用户消息触发一次级联对话：
        1. 追加用户消息到 History（skip_append 为 True 时跳过）
        2. 以指定的 response_characters 为初始响应者启动级联
           - 若为 None，默认所有 Agent 响应
        3. 收集所有回复，拼接最终展示文本

        visible_characters / response_characters 由用户从前端指定；
        未指定时默认对全体可见、全体响应。
        """
        if self.is_interrupted():
            return ""

        # 用户消息的可见角色
        _visible = visible_characters if visible_characters else self._agent_names
        # 初始响应角色
        _response = response_characters if response_characters else self._agent_names

        # 追加用户消息
        if not skip_append:
            self._history.add_message(
                CharacterConversationMessage.from_text(
                    role=Role.USER,
                    character_name=USER_CHARACTER_NAME,
                    text=user_message,
                    visible_characters=_visible,
                )
            )

        # 以用户指定的角色（或全体）作为初始响应者
        await self._cascade(_response)

        # 收集本轮所有 Agent 的回复（用户消息之后的消息）
        responses: list[str] = []
        for msg in self._history.messages:
            if isinstance(msg, CharacterConversationMessage) and msg.role == Role.ASSISTANT:
                if msg.character_name in self._agents:
                    text = msg.content if isinstance(msg.content, str) else str(msg.content)
                    responses.append(f"[{msg.character_name}]: {text}")

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
        depth: int = 0,
    ) -> None:
        """递归级联核心。

        并发启动所有 ``response_characters`` 指定的 Agent worker，
        按完成顺序串行写入 History，提取下一轮 response_characters，
        递归直到无人被指定或达到最大深度。

        最后一轮（depth == MAX-1）时：
        - 注入 final-round 提示词，告知 Agent 不得指定 response_characters
        - 代码层面强制忽略 Agent 输出的 response_characters
        """
        is_contains_main_agent = MAIN_AGENT_CHARACTER_NAME in response_characters
        # 运行时防御：过滤已删除 subagent profile 的角色
        response_characters = self._get_available_subagents(response_characters)
        # 恢复主agent, 因_get_available_subagents会删除主agent
        if is_contains_main_agent:
            response_characters.append(MAIN_AGENT_CHARACTER_NAME)

        if not response_characters or depth >= MULTI_AGENT_MAX_CASCADE_DEPTH:
            if depth >= MULTI_AGENT_MAX_CASCADE_DEPTH:
                logger.warning(
                    "Cascade depth limit (%d) reached for session=%s",
                    MULTI_AGENT_MAX_CASCADE_DEPTH,
                    self.session_id,
                )
            return

        # 是否最后一轮（下一轮将超过最大深度）
        is_final_round = (depth == MULTI_AGENT_MAX_CASCADE_DEPTH - 1)

        # 过滤不存在的 Agent 名
        valid_chars = [c for c in response_characters if c in self._agents]
        invalid_chars = set(response_characters) - set(valid_chars)
        if invalid_chars:
            logger.warning(
                "Ignoring unknown response_characters: %s", invalid_chars
            )

        if not valid_chars:
            return

        logger.debug(
            "Cascade depth=%d, agents=%s, final=%s, session=%s",
            depth, valid_chars, is_final_round, self.session_id,
        )

        # 并发启动所有 worker（最后一轮传递 is_final_round）
        tasks: list[asyncio.Task[WorkerResult]] = []
        for char_name in valid_chars:
            task = asyncio.create_task(
                self._run_single_agent(char_name, is_final_round=is_final_round),
                name=f"multi_agent_{char_name}_{depth}",
            )
            tasks.append(task)

        # 等待所有 worker 完成（任一失败不影响其他）
        results: list[WorkerResult] = []
        for task in asyncio.as_completed(tasks):
            try:
                result = await task
                results.append(result)
            except Exception:
                logger.exception(
                    "Agent worker failed for session=%s",
                    self.session_id,
                )

        if not results:
            return

        # 按完成顺序串行写入 History（_io_locker 保证线程安全）
        next_chars: set[str] = set()
        for result in results:
            parsed = result.parsed_json
            content_text = parsed.content
            visible = parsed.visible_characters
            response = list(parsed.response_characters)

            # 最后一轮：强制忽略 response_characters
            if is_final_round:
                response = []

            msg = CharacterConversationMessage(
                role=Role.ASSISTANT,
                character_name=result.character_name,
                content=str(content_text),
                visible_characters=visible if visible else None,
                response_characters=response if response else None,
                reasoning=None,
                reasoning_field_name="reasoning_content",
                tool_calls=None,
                message_suffix=None,
            )

            self._history.add_message(msg)

            # 收集下一轮需要响应的 Agent（最后一轮跳过）
            if not is_final_round:
                for rc in response:
                    if rc in self._agents:
                        next_chars.add(rc)

        # 递归触发下一轮级联
        await self._cascade(list(next_chars), depth + 1)

    # -- 单 Agent 执行 -----------------------------------------------------

    async def _run_single_agent(
        self, character_name: str, *, is_final_round: bool = False
    ) -> WorkerResult:
        """启动单个 Agent 的 tool loop + JSON 输出。

        委托给 MultiAgentWorker 执行完整的 LLM → tool_calls → tool_result → 循环。
        """
        profile = self._agents[character_name]

        # 构建该 Agent 视角的 History 视图
        history_view = self._history.get_messages(character_name)

        # 最后一轮：加载并追加 final-round 提示词后缀
        system_prompt = profile.system_prompt
        if is_final_round:
            global _Final_Round_Prompt
            if _Final_Round_Prompt is None:
                template_path = get_templates_dir() / "multiagent" / "multi_agent_final_round_prompt.txt"
                with open(template_path, "r", encoding="utf-8") as f:
                    _Final_Round_Prompt = f.read()
            system_prompt = system_prompt + "\n\n" + _Final_Round_Prompt

        worker = MultiAgentWorker(
            character_name=character_name,
            system_prompt=system_prompt,
            history=history_view,
            tools=profile.tools,
            llm_client=profile.llm_client,
            sink=self._sink,
            loop=self,
        )

        return await worker.run()