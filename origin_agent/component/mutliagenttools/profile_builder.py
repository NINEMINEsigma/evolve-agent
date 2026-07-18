"""
多 Agent 模式 Profile 构造器。

提取 enter_multi_agent.py 与 session_manager.py 中重复的
AgentProfile 构造逻辑，通过回调统一主/子 Agent 的构造路径。
"""

from __future__ import annotations

import logging
from typing import Callable, TYPE_CHECKING

from system.sandbox import Sandbox
from system.templates import render_multi_agent_prompt
from component.mutliagenttools._store import SubagentStore
from abstract.llm.client import BaseLLMClient
from entity.puretype import AgentConfig
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
    """返回多 Agent 模式下可用的工具定义。

    通过 availability scope 直接筛选，无需手动排除 toolset。
    """
    from entity.puretype import ToolAvailability

    return tool_registry.get_definitions_for_availability(
        scope=ToolAvailability.MULTI_AGENT,
    )


# ── system_prompts 解析回调类型 ──────────────────────────────────
# 统一签名：(name, config, parent_ctx, sandbox) -> list[str]
# 主 Agent：从模板系统生成人设提示词
# 子 Agent：从 config.system_prompt_paths 沙箱读取
SystemPromptsResolver = Callable[
    [str, AgentConfig, "RuntimeContext", Sandbox],
    list[str],
]


def _resolve_main_agent_prompts(
    _name: str,
    _config: AgentConfig,
    parent_ctx: RuntimeContext,
    _sandbox: Sandbox,
) -> list[str]:
    """主 Agent 的系统提示词解析：从模板系统生成。"""
    from entity.puretype import ToolAvailability

    skill_blocks = collect_skill_prompts()
    return build_agent_system_prompt(
        parent_ctx, skill_blocks,
        tool_availability_scope=ToolAvailability.MULTI_AGENT,
    )


def _resolve_subagent_prompts(
    name: str,
    config: AgentConfig,
    _parent_ctx: RuntimeContext,
    sandbox: Sandbox,
) -> list[str]:
    """子 Agent 的系统提示词解析：从 config.system_prompt_paths 沙箱读取。"""
    persona_prompts: list[str] = []
    for p in config.system_prompt_paths:
        if sandbox.exists(p):
            persona_prompts.append(sandbox.read(p, limit=0))
        else:
            logger.warning(
                "Subagent %s system prompt path not found: %s",
                name, p,
            )
    return persona_prompts


def build_agent_profiles(
    agents: list[str],
    main_agent_name: str,
    parent_ctx: RuntimeContext,
    llm_client_factory: Callable[[str, AgentConfig | None], BaseLLMClient],
    system_prompt_template: str,
    sandbox: Sandbox,
    store: SubagentStore,
    *,
    session_id: str = "",
    skip_missing_subagent: bool = False,
) -> dict[str, AgentProfile]:
    """为多 Agent 模式构造每个参与者的 AgentProfile。

    主/子 Agent 统一流程：
    1. 获取 AgentConfig：主 Agent 从 RuntimeContext 构造；子 Agent 从 SubagentStore 获取
    2. 解析 system_prompts：主 Agent 从模板系统生成；子 Agent 从沙箱路径读取
    3. 构造 llm_client：通过 llm_client_factory 回调统一
    4. 构造 AgentProfile（含 config 字段）

    Args:
        agents: 参与协作的 agent 名称列表。
        main_agent_name: 主 agent 名称。
        parent_ctx: 父 agent 的 RuntimeContext。
        llm_client_factory: 接收 (name, config_or_none) 返回 BaseLLMClient。
            主 agent 调用时 config_or_none 为 None；子 agent 调用时为 AgentConfig 实例。
        system_prompt_template: 多 Agent 协作模板原文。
        sandbox: 用于读取 system_prompt_paths 的沙盒实例。
        store: SubagentStore 实例。
        session_id: 用于日志。
        skip_missing_subagent: 为 True 时，子 agent config 缺失则跳过；
            为 False 时抛出 ValueError。

    Returns:
        dict[str, AgentProfile]: 以 agent 名为键的 AgentProfile 字典。
        tools 字段初始为空列表，由调用方回填。
    """
    agent_profiles: dict[str, AgentProfile] = {}

    for name in agents:
        multi_agent_common_prompt = render_multi_agent_prompt(system_prompt_template, name)

        # ── 1. 获取 AgentConfig ──
        if name == main_agent_name:
            # 主 Agent 从 RuntimeContext 构造 AgentConfig（不持久化）
            config = AgentConfig(
                base_url=parent_ctx.llm_base_url,
                model=parent_ctx.llm_model,
                api_key=parent_ctx.llm_api_key or None,
                system_prompt_paths=[],
                max_output_tokens=parent_ctx.llm_max_output_tokens,
                max_context_tokens=parent_ctx.llm_max_context_tokens,
                client_type=parent_ctx.llm_client_name,
            )
            llm_client = llm_client_factory(name, None)
        else:
            # 子 Agent 从 SubagentStore 获取
            config = store.get(name)
            if config is None and skip_missing_subagent:
                logger.warning(
                    "Subagent profile '%s' not found, skipping (session=%s)",
                    name, session_id,
                )
                continue
            if config is None:
                raise ValueError(
                    f"Subagent profile '{name}' not found (session={session_id}). "
                    "Register it first using register_subagent_from_parent."
                )
            llm_client = llm_client_factory(name, config)

        # ── 2. 解析 system_prompts（统一通过回调） ──
        if name == main_agent_name:
            persona_prompts = _resolve_main_agent_prompts(name, config, parent_ctx, sandbox)
        else:
            persona_prompts = _resolve_subagent_prompts(name, config, parent_ctx, sandbox)

        # ── 3. 构造 AgentProfile ──
        system_prompts = persona_prompts + [multi_agent_common_prompt]
        agent_profiles[name] = AgentProfile(
            character_name=name,
            system_prompts=system_prompts,
            tools=[],  # 由调用方在创建 MultiAgentLoop 前统一设置
            llm_client=llm_client,
            config=config,
        )

    return agent_profiles