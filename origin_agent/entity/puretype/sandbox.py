"""沙盒相关纯数据类型。"""

from pydantic import BaseModel, Field


class DynamicSandboxSpace(BaseModel):
    """单个全局动态沙盒空间配置。"""

    name: str
    path: str
    description: str
    is_readonly: bool = True


class DynamicSandboxSpaceData(BaseModel):
    """动态沙盒空间持久化根对象。"""

    spaces: list[DynamicSandboxSpace] = Field(default_factory=list)
