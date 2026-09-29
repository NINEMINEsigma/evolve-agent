"""多Agent模式的运行时 Profile 构造器。"""

from __future__ import annotations

import logging
from typing import Callable, Mapping, TYPE_CHECKING

from system.sandbox import Sandbox
from system.templates import render_multi_agent_prompt
from abstract.llm.client import BaseLLMClient
from entity.puretype import AgentConfig, CharacterProfile, LLMProfile
from entry.agent_support.messages import (
    build_agent_system_prompt,
    collect_skill_prompts,
)
from entry.multi_agent_loop import AgentProfile
from subagent.profile import (
    character_profile_to_agent_config,
    get_character_system_prompts,
)

if TYPE_CHECKING:
    from system.context import RuntimeContext
    from abstract.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def build_multi_agent_tools(tool_registry: ToolRegistry) -> list[dict]:
    """返回多Agent模式下可用的工具定义。"""
    from entity.puretype import ToolAvailability

    return tool_registry.get_definitions_for_availability(
        scope=ToolAvailability.MULTI_AGENT,
    )


SystemPromptsResolver = Callable[
    [str, AgentConfig, "RuntimeContext", Sandbox],
    list[str],
]


def _resolve_main_agent_prompts(
    _name: str,
    _config: AgentConfig,
    parent_ctx: RuntimeContext,
    _sandbox: Sandbox,
    profile: LLMProfile | None = None,
    session_id: str = "",
    loaded_toolsets: set[str] | None = None,
) -> list[str]:
    """主Agent的系统提示词解析：从模板系统生成人设提示词。"""
    from entity.puretype import ToolAvailability

    skill_blocks = collect_skill_prompts()
    return build_agent_system_prompt(
        parent_ctx,
        skill_blocks,
        tool_availability_scope=ToolAvailability.MULTI_AGENT,
        profile=profile,
        session_id=session_id,
        loaded_toolsets=loaded_toolsets,
    )


def _resolve_subagent_prompts(profile: CharacterProfile) -> list[str]:
    """返回动态角色档案声明的全部系统提示词。"""
    return get_character_system_prompts(profile)


def build_agent_profiles(
    agents: list[str],
    main_agent_name: str,
    parent_ctx: RuntimeContext,
    llm_client_factory: Callable[[str, LLMProfile | None], BaseLLMClient | None],
    system_prompt_template: str,
    sandbox: Sandbox,
    profiles: Mapping[str, CharacterProfile],
    *,
    session_id: str = "",
    skip_missing_subagent: bool = False,
    main_profile: LLMProfile | None = None,
) -> dict[str, AgentProfile]:
    """为多Agent模式构造每个参与者的运行时 Profile。

    主Agent从当前活动 Profile构造；子Agent从动态角色档案映射获取当前
    LLM Profile和 profile.md 正文。`AgentConfig` 只作为 MultiAgentWorker
    现有运行时接口的临时适配对象，不参与持久化。
    """
    agent_profiles: dict[str, AgentProfile] = {}

    for name in agents:
        multi_agent_common_prompt = render_multi_agent_prompt(system_prompt_template, name)

        if name == main_agent_name:
            if main_profile is None:
                defaults = LLMProfile()
                config = AgentConfig(
                    base_url="",
                    model="",
                    api_key=None,
                    system_prompt_paths=[],
                    max_output_tokens=defaults.max_output_tokens,
                    max_context_tokens=defaults.max_context_tokens,
                    client_type="",
                )
                llm_client = None
            else:
                config = AgentConfig(
                    base_url=main_profile.base_url,
                    model=main_profile.model,
                    api_key=main_profile.api_key or None,
                    system_prompt_paths=[],
                    max_output_tokens=main_profile.max_output_tokens,
                    max_context_tokens=main_profile.max_context_tokens,
                    client_type=main_profile.llm_client_name,
                )
                llm_client = llm_client_factory(name, main_profile)
            persona_prompts = _resolve_main_agent_prompts(
                name,
                config,
                parent_ctx,
                sandbox,
                profile=main_profile,
                session_id=session_id,
            )
            agent_llm_profile = main_profile
        else:
            character_profile = profiles.get(name)
            if character_profile is None:
                if skip_missing_subagent:
                    logger.warning(
                        "Character profile '%s' not found, skipping (session=%s)",
                        name,
                        session_id,
                    )
                    continue
                raise ValueError(
                    f"Character profile '{name}' not found (session={session_id})"
                )
            if character_profile.error is not None or character_profile.llm_profile is None:
                if skip_missing_subagent:
                    logger.warning(
                        "Character profile '%s' unavailable: %s (session=%s)",
                        name,
                        character_profile.error,
                        session_id,
                    )
                    continue
                raise ValueError(character_profile.error or f"Character profile '{name}' is unavailable")

            config = character_profile_to_agent_config(character_profile)
            agent_llm_profile = character_profile.llm_profile
            llm_client = llm_client_factory(name, agent_llm_profile)
            persona_prompts = _resolve_subagent_prompts(character_profile)

        system_prompts = persona_prompts + [multi_agent_common_prompt]
        agent_profiles[name] = AgentProfile(
            character_name=name,
            system_prompts=system_prompts,
            tools=[],
            llm_client=llm_client,
            config=config,
            llm_profile=agent_llm_profile,
        )

    return agent_profiles
