"""
泛型工具类型定义
"""

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class RefWrapper(BaseModel, Generic[T]):
    """可变引用容器，用于在多个组件间共享一个可变值。

    典型用途：循环计数器需要被 ToolExecutor 修改时，
    循环将计数器包装为 RefWrapper[int] 并注入 ToolExecutor，
    ToolExecutor 在特定条件下重置 value，循环读取 value 判断终止条件。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    value: T