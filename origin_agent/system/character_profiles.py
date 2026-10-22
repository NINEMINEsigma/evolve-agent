"""角色档案目录的纯函数组装。

每次调用通过 ``CharacterProfileResolver.discover()`` 实时扫描
``ws:characters/roleplay/`` 与 ``ws:characters/task/``，将档案映射为
``GET /api/characters/profiles`` 的脱敏响应模型。不缓存、不持久化、
不注册 System。

脱敏边界：``CharacterProfile.llm_profile`` 实例引用（含 API 密钥）与
``metadata`` 原始字典不出本模块；条目仅保留 Profile 名称。条目级
错误（缺失文件、重名、Profile 引用不可用等）已由 resolver 写入
``error`` 字段，本函数不做二次过滤，重名条目各自独立返回。
"""

from __future__ import annotations

import logging

from entity.puretype import CharacterProfileEntry, CharacterProfilesResponse
from interface.sandbox import ISandbox
from interface.llm_profile_store import ILLMProfileStore
from subagent.profile import CharacterProfileResolver

# 防御性声明：discover() 已捕获目录级/条目级异常进 error 字段，
# 映射过程为纯字段访问、无显著异常源；logger 仅作意外异常兜底日志。
logger = logging.getLogger(__name__)


def collect_character_profiles(
    sandbox: ISandbox, profile_store: ILLMProfileStore
) -> CharacterProfilesResponse:
    """实时扫描全部角色档案并映射为脱敏响应模型。"""
    resolver = CharacterProfileResolver(sandbox, profile_store)
    entries: list[CharacterProfileEntry] = []
    for profile in resolver.discover():
        entries.append(
            CharacterProfileEntry(
                name=profile.name,
                character_type=profile.character_type,
                directory_path=profile.directory_path,
                profile_path=profile.profile_path,
                system_prompt=profile.system_prompt,
                system_prompt_paths=profile.system_prompt_paths,
                system_prompts=profile.system_prompts,
                description=profile.description,
                llm_profile_name=profile.llm_profile_name,
                profile_available=(
                    profile.error is None and profile.llm_profile is not None
                ),
                error=profile.error,
            )
        )
    return CharacterProfilesResponse(characters=entries)
