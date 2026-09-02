"""LLM Profile v2 根对象存储。"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from easysave import contains, load, save

from entity.constant import (
    LLM_PROFILES_ES_FILENAME,
    LLM_PROFILES_ES_KEY,
)
from entity.puretype.llm import (
    LLMProfile,
    LLMProfileData,
    LLMProfilePayload,
)
from system.atomic_io import replace_atomic

logger = logging.getLogger(__name__)

_REFERENCE_FIELDS: tuple[str, ...] = (
    "vision_image_profile",
    "audio_profile",
    "vision_video_profile",
)
_PROFILE_FIELDS: tuple[str, ...] = (
    "name",
    "llm_client_name",
    "base_url",
    "model",
    "api_key",
    "temperature",
    "max_output_tokens",
    "reasoning_effort",
    "max_context_tokens",
    *_REFERENCE_FIELDS,
)


class LLMProfileStore:
    """进程内唯一的 ``LLMProfileData`` 根对象存储。"""

    def __init__(
        self,
        agentspace_dir: Path,
        lock: threading.RLock | None = None,
    ) -> None:
        self._agentspace_dir = Path(agentspace_dir)
        self._path = self._agentspace_dir / LLM_PROFILES_ES_FILENAME
        self._lock = lock or threading.RLock()
        with self._lock:
            self._data = self._load_unlocked()

    @property
    def path(self) -> Path:
        """返回 Profile 注册表路径。"""
        return self._path

    def get_data(self) -> LLMProfileData:
        """返回共享根对象；修改必须通过本类的写接口完成。"""
        with self._lock:
            return self._data

    def list_profiles(self) -> list[LLMProfile]:
        """返回根列表的浅拷贝，列表元素仍是根对象中的实例。"""
        with self._lock:
            return list(self._data.profiles)

    def get_profile(self, name: str) -> LLMProfile:
        """按名称返回根对象中的 Profile；未命中直接抛出 ``LookupError``。"""
        with self._lock:
            for profile in self._data.profiles:
                if profile.name == name:
                    return profile
        raise LookupError(f"LLM profile not found: {name!r}")

    def resolve_profile_name(self, name: str) -> LLMProfile | None:
        """空名称表示无配置；非空名称必须命中现有 Profile。"""
        if name == "":
            return None
        return self.get_profile(name)

    def to_payload(self, profile: LLMProfile) -> LLMProfilePayload:
        """将根对象中的 Profile 显式转换为扁平 HTTP DTO。"""
        with self._lock:
            return LLMProfilePayload(
                name=profile.name,
                llm_client_name=profile.llm_client_name,
                base_url=profile.base_url,
                model=profile.model,
                api_key=profile.api_key,
                temperature=profile.temperature,
                max_output_tokens=profile.max_output_tokens,
                reasoning_effort=profile.reasoning_effort,
                max_context_tokens=profile.max_context_tokens,
                vision_image_profile=(
                    profile.vision_image_profile.name
                    if profile.vision_image_profile is not None else None
                ),
                audio_profile=(
                    profile.audio_profile.name
                    if profile.audio_profile is not None else None
                ),
                vision_video_profile=(
                    profile.vision_video_profile.name
                    if profile.vision_video_profile is not None else None
                ),
            )

    def create_profile(self, payload: LLMProfilePayload) -> LLMProfile:
        """新增一个 Profile，并在成功后返回根列表中的新实例。"""
        if not isinstance(payload, LLMProfilePayload):
            raise TypeError("payload must be LLMProfilePayload")
        with self._lock:
            if not payload.name:
                raise ValueError("LLM profile name must not be empty")
            if any(p.name == payload.name for p in self._data.profiles):
                raise ValueError(f"Duplicate LLM profile name: {payload.name!r}")
            refs = self._resolve_payload_references(payload)
            profile = LLMProfile(
                name=payload.name,
                llm_client_name=payload.llm_client_name,
                base_url=payload.base_url,
                model=payload.model,
                api_key=payload.api_key,
                temperature=payload.temperature,
                max_output_tokens=payload.max_output_tokens,
                reasoning_effort=payload.reasoning_effort,
                max_context_tokens=payload.max_context_tokens,
                **refs,
            )
            self._data.profiles.append(profile)
            try:
                self._validate_root(self._data)
                self._save_unlocked()
            except Exception:
                self._data.profiles.pop()
                raise
            logger.info("Created LLM profile | name=%s", profile.name)
            return profile

    def update_profile(
        self,
        original_name: str,
        payload: LLMProfilePayload,
    ) -> LLMProfile:
        """原地更新 Profile；重命名不会替换实例身份。"""
        if not isinstance(payload, LLMProfilePayload):
            raise TypeError("payload must be LLMProfilePayload")
        with self._lock:
            profile = self.get_profile(original_name)
            if not payload.name:
                raise ValueError("LLM profile name must not be empty")
            if any(
                other is not profile and other.name == payload.name
                for other in self._data.profiles
            ):
                raise ValueError(f"Duplicate LLM profile name: {payload.name!r}")
            refs = self._resolve_payload_references(payload)
            old_values = self._snapshot_profile(profile)
            self._assign_payload(profile, payload, refs)
            try:
                self._validate_root(self._data)
                self._save_unlocked()
            except Exception:
                self._restore_profile(profile, old_values)
                raise
            logger.info(
                "Updated LLM profile | old_name=%s new_name=%s",
                original_name,
                profile.name,
            )
            return profile

    def assert_removable(self, profile: LLMProfile) -> None:
        """确认没有其他根 Profile 直接引用目标实例。"""
        with self._lock:
            for owner in self._data.profiles:
                if owner is profile:
                    continue
                for field in _REFERENCE_FIELDS:
                    if getattr(owner, field) is profile:
                        raise ValueError(
                            f"LLM profile {profile.name!r} is referenced by "
                            f"{owner.name!r}.{field}"
                        )

    def remove_profile(self, name: str) -> LLMProfile:
        """移除未被其他根 Profile 引用的实例。"""
        with self._lock:
            profile = self.get_profile(name)
            self.assert_removable(profile)
            index = self._data.profiles.index(profile)
            self._data.profiles.pop(index)
            try:
                self._validate_root(self._data)
                self._save_unlocked()
            except Exception:
                self._data.profiles.insert(index, profile)
                raise
            logger.info("Removed LLM profile | name=%s", name)
            return profile

    # ------------------------------------------------------------------
    # 加载、迁移与校验
    # ------------------------------------------------------------------

    def _load_unlocked(self) -> LLMProfileData:
        if not contains(LLM_PROFILES_ES_KEY, str(self._path)):
            return LLMProfileData()

        data = load(LLM_PROFILES_ES_KEY, str(self._path))
        if not isinstance(data, LLMProfileData):
            raise TypeError(
                f"Expected LLMProfileData in v2, got {type(data).__name__}"
            )
        self._validate_root(data)
        return data

    def _validate_root(self, data: LLMProfileData) -> None:
        if not isinstance(data, LLMProfileData):
            raise TypeError("Profile root must be LLMProfileData")
        if set(data.__dict__) - {"profiles"}:
            raise TypeError("LLMProfileData contains unknown fields")
        if not isinstance(data.profiles, list):
            raise TypeError("LLMProfileData.profiles must be a list")

        names: set[str] = set()
        profile_ids: set[int] = set()
        for profile in data.profiles:
            if not isinstance(profile, LLMProfile):
                raise TypeError("LLMProfileData.profiles must contain LLMProfile instances")
            self._validate_profile_scalars(profile)
            if not profile.name:
                raise ValueError("LLM profile name must not be empty")
            if profile.name in names:
                raise ValueError(f"Duplicate LLM profile name: {profile.name!r}")
            names.add(profile.name)
            profile_ids.add(id(profile))

        for profile in data.profiles:
            for field in _REFERENCE_FIELDS:
                reference = getattr(profile, field)
                if reference is None:
                    continue
                if not isinstance(reference, LLMProfile):
                    raise TypeError(f"{field} must be an LLMProfile or None")
                if id(reference) not in profile_ids:
                    raise ValueError(
                        f"Profile {profile.name!r} references an object outside the root"
                    )
                if reference is profile:
                    raise ValueError(
                        f"Profile {profile.name!r} cannot reference itself"
                    )

        visiting: set[int] = set()
        visited: set[int] = set()

        def visit(profile: LLMProfile) -> None:
            profile_id = id(profile)
            if profile_id in visiting:
                raise ValueError("Circular LLM profile reference detected")
            if profile_id in visited:
                return
            visiting.add(profile_id)
            for field in _REFERENCE_FIELDS:
                reference = getattr(profile, field)
                if reference is not None:
                    visit(reference)
            visiting.remove(profile_id)
            visited.add(profile_id)

        for profile in data.profiles:
            visit(profile)

    @staticmethod
    def _validate_profile_scalars(profile: LLMProfile) -> None:
        fields = set(profile.__dict__)
        if fields - set(_PROFILE_FIELDS):
            raise TypeError("LLMProfile contains unknown fields")
        string_fields = (
            "name",
            "llm_client_name",
            "base_url",
            "model",
            "api_key",
            "reasoning_effort",
        )
        for field in string_fields:
            if type(getattr(profile, field)) is not str:
                raise TypeError(f"LLMProfile.{field} must be a string")
        for field in ("max_output_tokens", "max_context_tokens"):
            if type(getattr(profile, field)) is not int:
                raise TypeError(f"LLMProfile.{field} must be an integer")
        temperature = getattr(profile, "temperature")
        if type(temperature) not in (int, float):
            raise TypeError("LLMProfile.temperature must be numeric")

    def _resolve_payload_references(
        self,
        payload: LLMProfilePayload,
    ) -> dict[str, LLMProfile | None]:
        resolved: dict[str, LLMProfile | None] = {}
        for field in _REFERENCE_FIELDS:
            name = getattr(payload, field)
            if name is None:
                resolved[field] = None
                continue
            if not isinstance(name, str) or not name:
                raise ValueError(f"{field} must be a Profile name or null")
            resolved[field] = self.get_profile(name)
        return resolved

    @staticmethod
    def _snapshot_profile(profile: LLMProfile) -> tuple[Any, ...]:
        return tuple(getattr(profile, field) for field in _PROFILE_FIELDS)

    @staticmethod
    def _restore_profile(profile: LLMProfile, values: tuple[Any, ...]) -> None:
        for field, value in zip(_PROFILE_FIELDS, values):
            setattr(profile, field, value)

    @staticmethod
    def _assign_payload(
        profile: LLMProfile,
        payload: LLMProfilePayload,
        refs: dict[str, LLMProfile | None],
    ) -> None:
        for field in (
            "name",
            "llm_client_name",
            "base_url",
            "model",
            "api_key",
            "temperature",
            "max_output_tokens",
            "reasoning_effort",
            "max_context_tokens",
        ):
            setattr(profile, field, getattr(payload, field))
        for field, value in refs.items():
            setattr(profile, field, value)

    # ------------------------------------------------------------------
    # v2 写入
    # ------------------------------------------------------------------

    def _save_unlocked(self, data: LLMProfileData | None = None) -> None:
        target = data if data is not None else self._data
        self._validate_root(target)
        self._agentspace_dir.mkdir(parents=True, exist_ok=True)

        if self._path.exists():
            original = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(original, dict):
                raise TypeError("LLM profile storage file must contain a JSON object")
        else:
            original = {}

        fd, temp_name = tempfile.mkstemp(
            prefix=f"{self._path.name}.",
            suffix=".tmp",
            dir=str(self._agentspace_dir),
            text=True,
        )
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            temp_path.write_text(
                json.dumps(original, ensure_ascii=False, indent=4),
                encoding="utf-8",
            )
            # 必须直接传递 LLMProfileData，保留 easysave 的对象引用图。
            save(LLM_PROFILES_ES_KEY, str(temp_path), target)
            replace_atomic(temp_path, self._path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
