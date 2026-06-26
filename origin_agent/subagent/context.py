"""子 Agent 运行时上下文 — 从注册表和调用参数构建。

与父 Agent 的 ``RuntimeContext`` 不同，``SubRuntimeContext`` 的 LLM 配置
全部来自子 Agent 注册表（``_store.py``）和 ``run_subagent`` 调用参数。
"""

from __future__ import annotations

from pydantic import BaseModel
from system.context import RuntimeContext
from system.sandbox import Sandbox


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

    system_prompt: str
    """系统提示词（来自注册表 system_prompt_paths 列表或内置默认模板）。"""


async def build_subagent_context(
    profile: dict,
    temperature: float,
    parent_ctx: RuntimeContext,
) -> SubRuntimeContext:
    """从注册表配置构建 SubRuntimeContext。

    Args:
        profile: 注册表中的子 Agent 配置字典。
        temperature: run_subagent 调用时传入的采样温度。
        parent_ctx: 父 Agent 的 RuntimeContext，用于创建沙盒实例解析路径。

    Returns:
        SubRuntimeContext 实例。

    Raises:
        FileNotFoundError: system_prompt_paths 中任一文件不存在。
        OSError: 读取 system_prompt_paths 中文件失败。
    """
    from system.templates import read_template

    # 1. 子 Agent 角色指令（你是父 Agent 的子会话，不是最终用户的对话对象）
    system_prompt: str = _default_system_prompt()

    # 2. 工具使用说明 — tools.txt 是纯工具使用规范（read_file vs run_command、
    #    edit_file vs write_file 的选择规则等），与主/子身份无关，必须传递
    tools_doc: str = read_template("tools.txt")
    if tools_doc:
        system_prompt = system_prompt + "\n\n" + tools_doc

    # 3. 用户自定义角色提示词 — 按注册表顺序追加到最后
    system_prompt_paths: list[str] = profile.get("system_prompt_paths") or []
    sandbox = Sandbox(parent_ctx)
    for prompt_path in system_prompt_paths:
        resolved = sandbox.resolve_read(prompt_path)
        if not resolved.real.exists():
            raise FileNotFoundError(
                f"System prompt file not found: {prompt_path}"
            )
        custom_prompt = resolved.real.read_text(encoding="utf-8").strip()
        if custom_prompt:
            system_prompt = system_prompt + "\n\n" + custom_prompt

    return SubRuntimeContext(
        base_url=str(profile.get("base_url", "")),
        model=str(profile.get("model", "")),
        api_key=profile.get("api_key"),
        temperature=temperature,
        max_output_tokens=int(profile.get("max_output_tokens", 0)),
        max_context_tokens=int(profile.get("max_context_tokens", 0)),
        system_prompt=system_prompt,
    )


def _default_system_prompt() -> str:
    """从模板文件读取内置默认系统提示词。

    模板路径：templates/subagent/subagent_system.txt
    """
    from system.templates import read_template
    prompt = read_template("subagent/subagent_system.txt")
    if not prompt:
        # 兜底：极简提示词
        return (
            "You are a sub-agent. Your user is the parent agent. "
            "Respond naturally; your messages are delivered to the parent agent automatically."
        )
    return prompt