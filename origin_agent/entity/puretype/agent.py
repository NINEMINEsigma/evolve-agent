from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Agent Config Types
# ---------------------------------------------------------------------------

class AgentConfig(BaseModel):
    """Agent 的可序列化配置，主 Agent 和子 Agent 共用。

    子 Agent 持久化到 agentspace/subagents/；主 Agent 在运行时从 RuntimeContext 构造，不持久化。
    """

    base_url: str
    """LLM API 端点地址。"""

    model: str
    """模型名称。"""

    api_key: str | None = None
    """API 密钥，本地模型可省略。"""

    system_prompt_paths: list[str] = Field(default_factory=list)
    """自定义系统提示词文件路径列表（沙箱逻辑路径）。"""

    max_output_tokens: int = 0
    """单次 LLM 输出的最大 token 数。"""

    max_context_tokens: int = 0
    """上下文窗口 token 上限，用于旋转控制。"""

    client_type: str = "openai_client"
    """LLM 客户端模块名，对应 custom_llm_client/<name>.py。"""