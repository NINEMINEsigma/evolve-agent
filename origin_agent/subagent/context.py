"""子Agent运行时上下文 — 从动态角色档案或临时Agent Profile构建。"""

from __future__ import annotations

from pydantic import BaseModel
from system.context import RuntimeContext

from entity.puretype import CharacterProfile, LLMProfile


class SubRuntimeContext(BaseModel):
    """子 Agent 的不可变运行时配置。

    普通角色子Agent由动态 CharacterProfile 构建，临时Agent由调用时的
    LLM Profile 快照构建。
    """

    base_url: str
    """子Agent的OpenAI兼容API端点地址（来自动态角色档案引用的Profile）。"""

    model: str
    """模型名称（来自注册表）。"""

    api_key: str | None = None
    """可选的 API 密钥。本地模型可省略（来自注册表）。"""

    temperature: float = 1.0
    """采样温度，钳制在 0.0–1.3（来自 run_subagent 调用参数）。"""

    max_output_tokens: int
    """单次LLM输出的最大 token 数（来自动态角色档案引用的Profile）。"""

    max_context_tokens: int
    """上下文窗口 token 上限，用于旋转控制（来自动态角色档案引用的Profile）。"""

    client_type: str = "openai_client"
    """LLM 客户端模块名；注册子Agent来自注册表，临时Agent来自活动 Profile快照。"""

    llm_profile: LLMProfile | None = None
    """临时Agent的非持久化 LLM Profile快照；注册子Agent为 None。"""

    system_prompts: list[str]
    """系统提示词列表（每项为独立 system message，来自注册表 system_prompt_paths 或内置默认模板）。"""

    tool_timeout: int = 30
    """单个工具调用允许运行的最大秒数，超时后取消（0 = 无超时）。"""


async def build_subagent_context(
    profile: CharacterProfile,
    temperature: float,
    parent_ctx: RuntimeContext,
) -> SubRuntimeContext:
    """从动态角色档案构建普通子Agent运行时上下文。"""
    from system.templates import read_template

    if profile.error is not None or profile.llm_profile is None:
        raise ValueError(
            profile.error or f"Character profile '{profile.name}' has no LLM Profile"
        )

    llm_profile = profile.llm_profile
    prompts: list[str] = [_default_system_prompt()]

    tools_doc: str = read_template("tools.txt")
    if tools_doc:
        prompts.append(tools_doc)

    if profile.system_prompt.strip():
        prompts.append(profile.system_prompt.strip())

    return SubRuntimeContext(
        base_url=llm_profile.base_url,
        model=llm_profile.model,
        api_key=llm_profile.api_key or None,
        temperature=temperature,
        max_output_tokens=llm_profile.max_output_tokens,
        max_context_tokens=llm_profile.max_context_tokens,
        client_type=llm_profile.llm_client_name,
        system_prompts=prompts,
    )


async def build_taskagent_context(
    profile: LLMProfile,
    parent_ctx: RuntimeContext,
) -> SubRuntimeContext:
    """从调用时活动 LLM Profile快照构建临时Agent上下文。

    Profile快照只在内存中使用，不属于注册子Agent配置，也不持久化。
    RuntimeContext仅提供工具超时等非 LLM运行参数。
    """
    if not profile.llm_client_name:
        raise ValueError(
            "The inherited LLM Profile has an empty LLM client module name"
        )

    return SubRuntimeContext(
        base_url=profile.base_url,
        model=profile.model,
        api_key=profile.api_key or None,
        temperature=profile.temperature,
        max_output_tokens=profile.max_output_tokens,
        max_context_tokens=profile.max_context_tokens,
        client_type=profile.llm_client_name,
        llm_profile=profile,
        system_prompts=[],
        tool_timeout=parent_ctx.tool_timeout,
    )


def _default_system_prompt() -> str:
    """从模板文件读取内置默认系统提示词。"""
    from system.templates import read_template
    return read_template("subagent/subagent_system.txt")