"""
多 Agent 模式 Profile 构造器。

提取 enter_multi_agent.py 与 session_manager.py 中重复的
AgentProfile 构造逻辑，通过 llm_client_factory 回调保留
两处对 LLM 客户端获取方式的差异。
"""

from __future__ import annotations

import logging
from typing import Any, Callable, TYPE_CHECKING

from system.sandbox import Sandbox
from system.templates import render_multi_agent_prompt
from component.mutliagenttools._store import SubagentStore
from abstract.llm.client import BaseLLMClient
from entity.puretype import SubagentProfile
from entry.agent_support.messages import (
    build_agent_system_prompt,
    collect_skill_prompts,
)
from entry.multi_agent_loop import AgentProfile

if TYPE_CHECKING:
    from system.context import RuntimeContext
    from abstract.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def build_multi_agent_tools(tool_registry: ToolRegistry) -> list[dict]:
    """返回多 Agent 模式下可用的工具定义：MAIN 工具集排除 multiagent 工具集。"""
    from entity.puretype import ToolAvailability

    tools = tool_registry.get_definitions_for_availability(scope=ToolAvailability.MAIN)
    multiagent_tool_names: set[str] = set(
        tool_registry.get_tool_names_for_toolset("multiagent"),
    )
    return [t for t in tools if t.get("function", {}).get("name") not in multiagent_tool_names]


def build_agent_profiles(
    agents: list[str],
    main_agent_name: str,
    parent_ctx: RuntimeContext,
    llm_client_factory: Callable[[str, SubagentProfile | None], BaseLLMClient],
    system_prompt_template: str,
    sandbox: Sandbox,
    store: SubagentStore,
    *,
    session_id: str = "",
    skip_missing_subagent: bool = False,
) -> dict[str, AgentProfile]:
    """为多 Agent 模式构造每个参与者的 AgentProfile。

    Args:
        agents: 参与协作的 agent 名称列表。
        main_agent_name: 主 agent 名称。
        parent_ctx: 父 agent 的 RuntimeContext。
        llm_client_factory: 接收 (name, profile_or_none) 返回 BaseLLMClient。
            主 agent 调用时 profile_or_none 为 None；子 agent 调用时为 SubagentProfile 实例。
        system_prompt_template: 多 Agent 协作模板原文。
        sandbox: 用于读取 system_prompt_paths 的沙盒实例。
        store: SubagentStore 实例。
        session_id: 用于日志。
        skip_missing_subagent: 为 True 时，子 agent profile 缺失则跳过；
            为 False 时构造空人设提示词列表。

    Returns:
        dict[str, AgentProfile]: 以 agent 名为键的 AgentProfile 字典。
        tools 字段初始为空列表，由调用方回填。
    """
    agent_profiles: dict[str, AgentProfile] = {}

    for name in agents:
        multi_agent_common_prompt = render_multi_agent_prompt(system_prompt_template, name)

        if name == main_agent_name:
            skill_blocks = collect_skill_prompts()
            persona_prompts = build_agent_system_prompt(parent_ctx, skill_blocks)
            llm_client = llm_client_factory(name, None)
        else:
            profile = store.get(name)
            if profile is None and skip_missing_subagent:
                logger.warning(
                    "Subagent profile '%s' not found, skipping (session=%s)",
                    name, session_id,
                )
                continue
            if profile is None:
                raise ValueError(
                    f"Subagent profile '{name}' not found (session={session_id}). "
                    "Register it first using register_subagent_from_parent."
                )
            prompt_paths = profile.system_prompt_paths
            persona_prompts: list[str] = []
            for p in prompt_paths:
                if sandbox.exists(p):
                    persona_prompts.append(sandbox.read(p, limit=0))
                else:
                    logger.warning(
                        "Subagent %s system prompt path not found: %s (session=%s)",
                        name, p, session_id,
                    )
            llm_client = llm_client_factory(name, profile)

        system_prompts = persona_prompts + [multi_agent_common_prompt]
        agent_profiles[name] = AgentProfile(
            character_name=name,
            system_prompts=system_prompts,
            tools=[],  # 由调用方在创建 MultiAgentLoop 前统一设置
            llm_client=llm_client,
        )

    return agent_profiles