"""角色头像映射的纯函数组装。

主Agent头像声明在 ``ws:SOUL.md.meta`` 的 ``[avatar]`` 键，子Agent头像
声明在角色目录 ``profile.md.meta`` 的 ``[avatar]`` 键。本模块每次调用
实时读取并校验声明，产出「角色名 → /files URL」映射条目；不缓存、
不持久化、不注册 System。头像属可选展示配置，声明存在但校验失败时
仅以条目级 ``error`` 返回（沿用 SOUL meta 读取的 Fail-Soft 边界），
不阻断整批结果。
"""

from __future__ import annotations

import logging
from urllib.parse import quote

from entity.constant import (
    AVATAR_MAX_BYTES,
    CHARACTERS_DIR_NAME,
    CHARACTER_AVATAR_META_KEY,
    CHARACTER_PROFILE_META_FILENAME,
    CHARACTER_ROLEPLAY_DIR_NAME,
    CHARACTER_TASK_DIR_NAME,
    SOUL_META_AVATAR_KEY,
    STATIC_FILE_HTTP_PREFIX,
)
from entity.puretype import CharacterAvatarEntry, CharacterAvatarsResponse
from system.file_metadata import MetaFormatError, parse_meta_content
from system.runtime import RuntimeSystem
from system.sandbox import Sandbox, SandboxError

logger = logging.getLogger(__name__)

# 与 RefreshIdentity / 主Agent身份读取一致的固定 SOUL 文件名口径。
_SOUL_FILE: str = "SOUL.md"


def avatar_files_url(logical_path: str) -> str:
    """将沙盒逻辑路径拼为 /files HTTP URL；路径不含命名空间时抛 ValueError。"""
    namespace, separator, relative = logical_path.partition(":")
    if not separator or not namespace or not relative:
        raise ValueError(f"Logical path has no namespace prefix: {logical_path!r}")
    path = "/".join(quote(part, safe="") for part in relative.split("/"))
    return f"{STATIC_FILE_HTTP_PREFIX}/{quote(namespace, safe='')}/{path}"


def _validated_avatar_entry(
    name: str,
    declared_path: str,
    sandbox: Sandbox
    ) -> CharacterAvatarEntry:
    """对已声明的 [avatar] 路径执行 resolve_read / is_file / 大小三重校验并产出条目。"""
    path = declared_path.strip()
    if not path:
        return CharacterAvatarEntry(name=name)
    try:
        resolved = sandbox.resolve_read(path)
        if not resolved.real.is_file():
            raise SandboxError(f"Avatar path is not a file: {path}")
        if resolved.real.stat().st_size > AVATAR_MAX_BYTES:
            raise SandboxError(
                f"Avatar file exceeds {AVATAR_MAX_BYTES} byte limit: {path}"
            )
    except SandboxError as exc:
        return CharacterAvatarEntry(name=name, avatar_path=path, error=str(exc))
    except OSError as exc:
        # 解析成功后的 stat/访问竞态归入条目级错误，不上抛。
        return CharacterAvatarEntry(
            name=name, avatar_path=path, error=f"Avatar file check failed: {exc}"
        )
    return CharacterAvatarEntry(
        name=name, avatar_path=path, avatar_url=avatar_files_url(path)
    )


def collect_main_agent_avatar(
    sandbox: Sandbox, runtime: RuntimeSystem
) -> CharacterAvatarEntry:
    """读 ws:SOUL.md.meta 的 [avatar]；meta 缺失/解析失败按无头像条目返回（带 error）。"""
    name = runtime.main_agent_character_name
    meta_logical = f"ws:{_SOUL_FILE}.meta"
    if not sandbox.exists(meta_logical):
        # 未创建 meta 文件属正常未配置，无 error。
        return CharacterAvatarEntry(name=name)
    try:
        content = sandbox.read(meta_logical, limit=0)
        metadata = parse_meta_content(content)
        declared = metadata.get(SOUL_META_AVATAR_KEY, "")
        first_line = declared.strip().splitlines()[0].strip() if declared.strip() else ""
    except (SandboxError, MetaFormatError) as exc:
        logger.warning("Failed to read %s for avatar: %s", meta_logical, exc)
        return CharacterAvatarEntry(name=name, error=str(exc))
    if not first_line:
        return CharacterAvatarEntry(name=name)
    return _validated_avatar_entry(name, first_line, sandbox)


def collect_character_avatars(
    sandbox: Sandbox, runtime: RuntimeSystem
) -> CharacterAvatarsResponse:
    """轻量扫描 ws:characters/roleplay/ 与 ws:characters/task/，逐目录产出条目。"""
    main_entry = collect_main_agent_avatar(sandbox, runtime)
    entries: list[CharacterAvatarEntry] = []
    for type_dir in (CHARACTER_ROLEPLAY_DIR_NAME, CHARACTER_TASK_DIR_NAME):
        root = f"ws:{CHARACTERS_DIR_NAME}/{type_dir}"
        try:
            names = sandbox.list_dir(root)
        except SandboxError:
            # 目录缺失或不可读属该类型无角色，正常跳过。
            continue
        for directory_name in names:
            directory_path = f"{root}/{directory_name}"
            try:
                if not sandbox.is_dir(directory_path):
                    continue
            except SandboxError:
                continue
            entries.append(
                _load_character_avatar_entry(directory_name, directory_path, sandbox)
            )
    return CharacterAvatarsResponse(main=main_entry, characters=entries)


def _load_character_avatar_entry(
    name: str,
    directory_path: str,
    sandbox: Sandbox
    ) -> CharacterAvatarEntry:
    """读取单个角色目录的 profile.md.meta 并解析 [avatar] 单键。

    只做头像轻量扫描：不读取 profile.md 正文，不解析 [profile] 与
    [llm_profile]；角色是否可运行与头像条目互不影响。
    """
    meta_logical = f"{directory_path}/{CHARACTER_PROFILE_META_FILENAME}"
    if not sandbox.exists(meta_logical):
        # 未创建 meta 的目录不是可运行角色，但也无头像声明可读。
        return CharacterAvatarEntry(name=name)
    try:
        content = sandbox.read(meta_logical, limit=0)
        metadata = parse_meta_content(content)
        declared = metadata.get(CHARACTER_AVATAR_META_KEY, "")
        first_line = declared.strip().splitlines()[0].strip() if declared.strip() else ""
    except (SandboxError, MetaFormatError) as exc:
        return CharacterAvatarEntry(name=name, error=str(exc))
    if not first_line:
        return CharacterAvatarEntry(name=name)
    return _validated_avatar_entry(name, first_line, sandbox)
