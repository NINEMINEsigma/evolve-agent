"""动态沙盒空间管理 REST 请求类型。"""

from pydantic import BaseModel, ConfigDict


class DynamicSandboxSpaceCreateRequest(BaseModel):
    """创建动态沙盒空间的完整配置。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    path: str
    description: str
    is_readonly: bool


class DynamicSandboxSpaceUpdateRequest(BaseModel):
    """更新动态沙盒空间的完整配置；名称由 Gateway 与路径参数核对。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    path: str
    description: str
    is_readonly: bool
