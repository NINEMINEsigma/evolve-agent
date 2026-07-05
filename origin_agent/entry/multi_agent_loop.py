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

    async def process_message(self, user_message: str) -> str:
        """处理用户消息入口。

        每轮用户消息触发一次级联对话：
        1. 追加用户消息到 History
        2. 以所有 Agent 为初始响应者启动级联
        3. 收集所有回复，拼接最终展示文本
        """
        if self.is_interrupted():
            return ""

        # 追加用户消息（对所有 Agent 可见，所有 Agent 应响应）
        self._history.add_message(
            CharacterConversationMessage.from_text(
                role=Role.USER,
                character_name=USER_CHARACTER_NAME,
                text=user_message,
                visible_characters=self._agent_names,
            )
        )

        # 所有 Agent 作为初始响应者
        await self._cascade(self._agent_names)

        # 收集本轮所有 Agent 的回复（用户消息之后的消息）
        responses: list[str] = []
        for msg in self._history.messages:
            if isinstance(msg, CharacterConversationMessage) and msg.role == Role.ASSISTANT:
                if msg.character_name in self._agents:
                    text = msg.content if isinstance(msg.content, str) else str(msg.content)
                    responses.append(f"[{msg.character_name}]: {text}")

        return "\n\n".join(responses) if responses else ""

    # -- 级联调度 ----------------------------------------------------------

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