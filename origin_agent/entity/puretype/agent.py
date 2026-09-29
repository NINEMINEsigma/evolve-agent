from typing import Literal

from pydantic import BaseModel, Field

from .llm import LLMProfile

# ---------------------------------------------------------------------------
# Agent Config Types
# ---------------------------------------------------------------------------

class AgentConfig(BaseModel):
    """Agent运行时适配配置，主Agent和多Agent运行时共用。

    子Agent角色不再将此类型持久化为注册项；角色目录和 LLM Profile
    在每次启动时动态解析后，必要时临时转换为此类型。
    """

    base_url: str
    """LLM API端点地址。"""

    model: str
    """模型名称。"""

    api_key: str | None = None
    """API密钥，本地模型可省略。"""

    system_prompt_paths: list[str] = Field(default_factory=list)
    """自定义系统提示词文件路径列表（沙盒逻辑路径）。"""

    max_output_tokens: int = 0
    """单次LLM输出的最大 token 数。"""

    max_context_tokens: int = 0
    """上下文窗口 token 上限，用于旋转控制。"""

    client_type: str = "openai_client"
    """LLM客户端模块名，对应 custom_llm_client/<name>.py。"""


class CharacterProfile(BaseModel):
    """从角色目录动态解析出的子Agent档案。"""

    name: str
    """角色目录名，也是全局唯一的子Agent名称。"""

    character_type: Literal["roleplay", "task"]
    """角色目录所属类型。"""

    directory_path: str
    """角色目录的逻辑路径。"""

    profile_path: str
    """角色档案文件的逻辑路径。"""

    system_prompt: str = ""
    """profile.md的完整正文。"""

    system_prompt_paths: list[str] = Field(default_factory=list)
    """profile.md.meta的[profile]字段声明的附加系统提示词逻辑路径。"""

    system_prompts: list[str] = Field(default_factory=list)
    """按声明顺序加载的系统提示词正文，首项通常来自profile.md。"""

    metadata: dict[str, str] = Field(default_factory=dict)
    """profile.md.meta解析后的元数据。"""

    llm_profile_name: str = ""
    """profile.md.meta中引用的LLM Profile名称。"""

    llm_profile: LLMProfile | None = None
    """当前LLM Profile根对象中的实例引用，不用于持久化。"""

    error: str | None = None
    """档案不可用时的可展示错误。"""
