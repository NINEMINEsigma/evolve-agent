"""动态角色档案发现与运行时适配。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from entity.constant import (
    CHARACTER_LLM_PROFILE_META_KEY,
    CHARACTER_PROFILE_FILENAME,
    CHARACTER_PROFILE_META_FILENAME,
    CHARACTER_ROLEPLAY_DIR_NAME,
    CHARACTER_TASK_DIR_NAME,
    CHARACTERS_DIR_NAME,
    SUBAGENT_NAME_PATTERN,
)
from entity.puretype import AgentConfig, CharacterProfile
from system.file_metadata import MetaFormatError, parse_meta_content
from system.sandbox import Sandbox, SandboxError

if TYPE_CHECKING:
    from system.llm_profile_store import LLMProfileStore


class CharacterProfileError(ValueError):
    """角色档案不存在、无效或引用不可用 Profile。"""


class CharacterProfileResolver:
    """每次调用都从工作空间动态读取角色档案的解析器。"""

    def __init__(self, sandbox: Sandbox, profile_store: LLMProfileStore) -> None:
        self._sandbox = sandbox
        self._profile_store = profile_store

    def discover(self) -> list[CharacterProfile]:
        """扫描所有角色类型并返回有效或带错误的档案条目。"""
        profiles: list[CharacterProfile] = []
        for character_type, type_dir in (
            ("roleplay", CHARACTER_ROLEPLAY_DIR_NAME),
            ("task", CHARACTER_TASK_DIR_NAME),
        ):
            root = f"ws:{CHARACTERS_DIR_NAME}/{type_dir}"
            try:
                root_resolved = self._sandbox.resolve_read(root)
                if not root_resolved.real.exists():
                    continue
                names = self._sandbox.list_dir(root)
            except SandboxError:
                continue

            for name in names:
                directory_path = f"{root}/{name}"
                try:
                    if not self._sandbox.is_dir(directory_path):
                        continue
                except SandboxError:
                    continue
                profiles.append(
                    self._load_profile(
                        name=name,
                        character_type=character_type,
                        directory_path=directory_path,
                    )
                )

        self._mark_duplicate_names(profiles)
        return profiles

    def get(self, name: str) -> CharacterProfile | None:
        """返回唯一且可用的角色档案；未命中或无效时返回 None。"""
        matches = [profile for profile in self.discover() if profile.name == name]
        if len(matches) != 1 or matches[0].error is not None:
            return None
        return matches[0]

    def require(self, name: str) -> CharacterProfile:
        """获取可运行角色，否则抛出可直接展示的错误。"""
        matches = [profile for profile in self.discover() if profile.name == name]
        if not matches:
            raise CharacterProfileError(f"Character profile not found: {name!r}")
        if len(matches) > 1:
            paths = ", ".join(profile.directory_path for profile in matches)
            raise CharacterProfileError(
                f"Character name '{name}' is duplicated across role types: {paths}"
            )
        profile = matches[0]
        if profile.error is not None:
            raise CharacterProfileError(profile.error)
        return profile

    def _load_profile(
        self,
        *,
        name: str,
        character_type: str,
        directory_path: str,
    ) -> CharacterProfile:
        profile_path = f"{directory_path}/{CHARACTER_PROFILE_FILENAME}"
        metadata_path = f"{directory_path}/{CHARACTER_PROFILE_META_FILENAME}"
        metadata: dict[str, str] = {}
        system_prompt = ""
        llm_profile_name = ""
        error: str | None = None

        if not re.fullmatch(SUBAGENT_NAME_PATTERN, name):
            error = f"Invalid character name: {name!r}"

        try:
            if not self._sandbox.exists(profile_path):
                raise CharacterProfileError(f"Character profile file not found: {profile_path}")
            system_prompt = self._sandbox.read(profile_path, limit=0)
        except (SandboxError, CharacterProfileError) as exc:
            error = error or str(exc)

        try:
            if not self._sandbox.exists(metadata_path):
                raise CharacterProfileError(
                    f"Character profile metadata file not found: {metadata_path}"
                )
            metadata = parse_meta_content(self._sandbox.read(metadata_path, limit=0))
            llm_profile_name = metadata.get(CHARACTER_LLM_PROFILE_META_KEY, "").strip()
            if not llm_profile_name:
                raise CharacterProfileError(
                    f"Missing [{CHARACTER_LLM_PROFILE_META_KEY}] in {metadata_path}"
                )
        except MetaFormatError as exc:
            error = error or f"Invalid character profile metadata {metadata_path}: {exc}"
        except (SandboxError, CharacterProfileError) as exc:
            error = error or str(exc)

        llm_profile = None
        if error is None:
            try:
                llm_profile = self._profile_store.resolve_profile_name(llm_profile_name)
                if llm_profile is None:
                    raise LookupError("empty LLM Profile name")
            except Exception as exc:
                error = (
                    f"LLM Profile {llm_profile_name!r} for character {name!r} "
                    f"is unavailable: {exc}"
                )

        return CharacterProfile(
            name=name,
            character_type=character_type,  # type: ignore[arg-type]
            directory_path=directory_path,
            profile_path=profile_path,
            system_prompt=system_prompt,
            metadata=metadata,
            llm_profile_name=llm_profile_name,
            llm_profile=llm_profile,
            error=error,
        )

    @staticmethod
    def _mark_duplicate_names(profiles: list[CharacterProfile]) -> None:
        by_name: dict[str, list[CharacterProfile]] = {}
        for profile in profiles:
            by_name.setdefault(profile.name, []).append(profile)
        for name, matches in by_name.items():
            if len(matches) < 2:
                continue
            paths = ", ".join(profile.directory_path for profile in matches)
            message = f"Character name '{name}' is duplicated across role types: {paths}"
            for profile in matches:
                profile.error = profile.error or message


def character_profile_to_agent_config(profile: CharacterProfile) -> AgentConfig:
    """将动态角色档案转换为仅供运行时使用的 AgentConfig。"""
    if profile.error is not None or profile.llm_profile is None:
        raise CharacterProfileError(
            profile.error or f"Character profile '{profile.name}' has no LLM Profile"
        )
    llm_profile = profile.llm_profile
    return AgentConfig(
        base_url=llm_profile.base_url,
        model=llm_profile.model,
        api_key=llm_profile.api_key or None,
        system_prompt_paths=[profile.profile_path],
        max_output_tokens=llm_profile.max_output_tokens,
        max_context_tokens=llm_profile.max_context_tokens,
        client_type=llm_profile.llm_client_name,
    )
