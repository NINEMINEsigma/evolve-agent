"""easysave 类型稳定名映射注册表。

为关键持久化类型分配版本化稳定名（format: "{version}::{ClassName}"），
使未来类名变更或模块移动后旧文件仍可通过 namespace 别名加载。

typespace（Type→稳定名）用于保存时写出稳定名；
namespace（稳定名→Type + 旧格式别名→Type）用于加载时反查类型。
make_config() 封装 EasySaveConfig 构造，供所有 easysave 调用点使用。
"""
from __future__ import annotations

from pathlib import Path
from typing import Type

from easysave import EasySaveConfig

from entity.constant import (
    History_Type_Version,
    LLMProfileData_Type_Version,
    AgentConfig_Type_Version,
)
from entity.messages import History
from entity.puretype.llm import LLMProfileData
from entity.puretype.agent import AgentConfig

# Type → 稳定名（保存时使用）
typespace: dict[Type, str] = {
    History: f"{History_Type_Version}::{History.__name__}",
    LLMProfileData: f"{LLMProfileData_Type_Version}::{LLMProfileData.__name__}",
    AgentConfig: f"{AgentConfig_Type_Version}::{AgentConfig.__name__}",
}

# 稳定名 → Type（加载时使用）
namespace: dict[str, Type] = {
    f"{History_Type_Version}::{History.__name__}": History,
    f"{LLMProfileData_Type_Version}::{LLMProfileData.__name__}": LLMProfileData,
    f"{AgentConfig_Type_Version}::{AgentConfig.__name__}": AgentConfig,
}


def make_config(path: str | Path) -> EasySaveConfig:
    """构造带有项目类型映射的 EasySaveConfig。"""
    return EasySaveConfig(
        path=str(path),
        typespace=typespace,
        namespace=namespace,
    )
