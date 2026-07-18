"""子 Agent 运行时上下文 — 从注册表和调用参数构建。

与父 Agent 的 ``RuntimeContext`` 不同，``SubRuntimeContext`` 的 LLM 配置
全部来自子 Agent 注册表（``_store.py``）和 ``run_subagent`` 调用参数。
"""

from __future__ import annotations

from pydantic import BaseModel
from system.context import RuntimeContext
from system.sandbox import Sandbox

from entity.puretype import AgentConfig


class SubRuntimeContext(BaseModel):
    """子 Agent 的不可变运行时配置。

    由 SubAgentOrchestrator.launch() 在每次启动时构建。
    """

    base_url: str
    """子 Agent 的 OpenAI 兼容 API 端点地址（来自注册表）。"""

    model: str
    """模型名称（来自注册表）。"""

    api_key: str | None = None
    """可选的 API 密钥。本地模型可省略（来自注册表）。"""

    temperature: float = 1.0
    """采样温度，钳制在 0.0–1.3（来自 run_subagent 调用参数）。"""

    max_output_tokens: int
    """单次 LLM 输出的最大 token 数（来自注册表）。"""

    max_context_tokens: int
    """上下文窗口 token 上限，用于旋转控制（来自注册表）。"""

    client_type: str = "openai_client"
    """LLM 客户端模块名，继承自主 Agent（来自注册表或 RuntimeContext 兜底）。"""

    system_prompts: list[str]
    """系统提示词列表（每项为独立 system message，来自注册表 system_prompt_paths 或内置默认模板）。"""

    tool_timeout: int = 30
    """单个工具调用允许运行的最大秒数，超时后取消（0 = 无超时）。"""


async def build_subagent_context(
    profile: AgentConfig,
    temperature: float,
    parent_ctx: RuntimeContext,
) -> SubRuntimeContext:
    """从注册表配置构建 SubRuntimeContext。

    Args:
        profile: 子 Agent 注册配置（AgentConfig）。
        temperature: run_subagent 调用时传入的采样温度。
        parent_ctx: 父 Agent 的 RuntimeContext，用于创建沙盒实例解析路径。

    Returns:
        SubRuntimeContext 实例。

    Raises:
        FileNotFoundError: system_prompt_paths 中任一文件不存在。
        OSError: 读取 system_prompt_paths 中文件失败。
    """
    from system.templates import read_template

    # 1. 子 Agent 角色指令
    prompts: list[str] = [_default_system_prompt()]

    # 2. 工具使用说明
    tools_doc: str = read_template("tools.txt")
    if tools_doc:
        prompts.append(tools_doc)

    # 3. 用户自定义角色提示词
    system_prompt_paths: list[str] = profile.system_prompt_paths
    sandbox = Sandbox(parent_ctx)
    for prompt_path in system_prompt_paths:
        resolved = sandbox.resolve_read(prompt_path)
        if not resolved.real.exists():
            raise FileNotFoundError(
                f"System prompt file not found: {prompt_path}"
            )
        custom_prompt = resolved.real.read_text(encoding="utf-8").strip()
        if custom_prompt:
            prompts.append(custom_prompt)

    return SubRuntimeContext(
        base_url=profile.base_url,
        model=profile.model,
        api_key=profile.api_key,
        temperature=temperature,
        max_output_tokens=profile.max_output_tokens,
        max_context_tokens=profile.max_context_tokens,
        client_type=profile.client_type,
        system_prompts=prompts,
    )


def _default_system_prompt() -> str:
    """从模板文件读取内置默认系统提示词。"""
    from system.templates import read_template
    return read_template("subagent/subagent_system.txt")