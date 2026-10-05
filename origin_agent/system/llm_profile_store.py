"""LLM Profile v2 根对象存储。"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Literal

from easysave import EasySaveBackupCleanupError, contains, load, save
from entity.typeref import make_config

from entity.constant import (
    LLM_PROFILE_BACKUP_CLEANUP_DELAY_SECONDS,
    LLM_PROFILE_BACKUP_CLEANUP_RETRIES,
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

    def get_approval_profile(self) -> LLMProfile | None:
        """返回根对象当前指向的审批 Profile 实例。"""
        with self._lock:
            return self._data.approval_profile

    def set_approval_profile(self, profile: LLMProfile | None) -> None:
        """设置根对象审批 Profile 引用并持久化。"""
        with self._lock:
            if profile is not None and not any(
                candidate is profile for candidate in self._data.profiles
            ):
                raise ValueError(
                    "LLMProfileData.approval_profile must reference a profile in profiles"
                )
            previous = self._data.approval_profile
            self._data.approval_profile = profile
            try:
                self._save_unlocked()
            except Exception:
                self._data.approval_profile = previous
                raise

    def is_approval_profile(self, profile: LLMProfile) -> bool:
        """返回 Profile 是否是根对象当前的审批 Profile 实例。"""
        with self._lock:
            return self._data.approval_profile is profile

    def get_metadata_profile(self) -> LLMProfile | None:
        """返回根对象当前指向的全局元数据 Profile 实例。"""
        with self._lock:
            return self._data.metadata_profile

    def set_metadata_profile(self, profile: LLMProfile | None) -> None:
        """设置根对象全局元数据 Profile 引用并持久化。"""
        with self._lock:
            if profile is not None and not any(
                candidate is profile for candidate in self._data.profiles
            ):
                raise ValueError(
                    "LLMProfileData.metadata_profile must reference a profile in profiles"
                )
            previous = self._data.metadata_profile
            self._data.metadata_profile = profile
            try:
                self._save_unlocked()
            except Exception:
                self._data.metadata_profile = previous
                raise

    def is_metadata_profile(self, profile: LLMProfile) -> bool:
        """返回 Profile 是否是根对象当前的全局元数据 Profile 实例。"""
        with self._lock:
            return self._data.metadata_profile is profile

    def get_global_modality_profile(
        self,
        media_type: Literal["image", "audio", "video"],
    ) -> LLMProfile | None:
        """返回指定媒体类型的全局回退 Profile 实例。"""
        with self._lock:
            if media_type == "image":
                return self._data.global_vision_image_profile
            if media_type == "audio":
                return self._data.global_audio_profile
            if media_type == "video":
                return self._data.global_vision_video_profile
            raise ValueError(f"Unsupported modality type: {media_type!r}")

    def set_global_modality_profile(
        self,
        media_type: Literal["image", "audio", "video"],
        profile: LLMProfile | None,
    ) -> None:
        """设置指定媒体类型的全局回退 Profile 引用并持久化。"""
        with self._lock:
            if profile is not None and not any(
                candidate is profile for candidate in self._data.profiles
            ):
                raise ValueError(
                    f"LLMProfileData global {media_type} profile must reference "
                    "a profile in profiles"
                )
            if media_type == "image":
                previous = self._data.global_vision_image_profile
                self._data.global_vision_image_profile = profile
            elif media_type == "audio":
                previous = self._data.global_audio_profile
                self._data.global_audio_profile = profile
            elif media_type == "video":
                previous = self._data.global_vision_video_profile
                self._data.global_vision_video_profile = profile
            else:
                raise ValueError(f"Unsupported modality type: {media_type!r}")
            try:
                self._save_unlocked()
            except Exception:
                if media_type == "image":
                    self._data.global_vision_image_profile = previous
                elif media_type == "audio":
                    self._data.global_audio_profile = previous
                else:
                    self._data.global_vision_video_profile = previous
                raise

    def is_global_modality_profile(
        self,
        profile: LLMProfile,
        media_type: Literal["image", "audio", "video"],
    ) -> bool:
        """返回 Profile 是否是指定媒体类型的全局回退 Profile。"""
        return self.get_global_modality_profile(media_type) is profile

    def is_any_global_modality_profile(self, profile: LLMProfile) -> bool:
        """返回 Profile 是否被任一全局多模态引用指向。"""
        with self._lock:
            return (
                self._data.global_vision_image_profile is profile
                or self._data.global_audio_profile is profile
                or self._data.global_vision_video_profile is profile
            )

    def list_profiles(self) -> list[LLMProfile]:
        """返回根列表的浅拷贝，列表元素仍是根对象中的实例。"""
        with self._lock:
            return list(self._data.profiles)

    def snapshot_profile(self, profile: LLMProfile) -> LLMProfile:
        """返回根对象中指定 Profile 的调用时深快照。"""
        with self._lock:
            if not any(candidate is profile for candidate in self._data.profiles):
                raise ValueError(
                    "Active LLM Profile does not belong to the current LLM Profile root"
                )
            return profile.model_copy(deep=True)

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
                soul_file=profile.soul_file,
            )

    def create_profile(self, payload: LLMProfilePayload) -> LLMProfile:
        """新增一个 Profile，并在成功后返回根列表中的新实例。"""
        with self._lock:
            if not payload.name:
                raise ValueError("LLM profile name must not be empty")
            if any(p.name == payload.name for p in self._data.profiles):
                raise ValueError(f"Duplicate LLM profile name: {payload.name!r}")
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
                vision_image_profile=self._resolve_profile_reference(
                    payload.vision_image_profile,
                ),
                audio_profile=self._resolve_profile_reference(
                    payload.audio_profile,
                ),
                vision_video_profile=self._resolve_profile_reference(
                    payload.vision_video_profile,
                ),
                soul_file=payload.soul_file,
            )
            self._data.profiles.append(profile)
            try:
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
        with self._lock:
            profile = self.get_profile(original_name)
            if not payload.name:
                raise ValueError("LLM profile name must not be empty")
            if any(
                other is not profile and other.name == payload.name
                for other in self._data.profiles
            ):
                raise ValueError(f"Duplicate LLM profile name: {payload.name!r}")
            old_values = self._snapshot_profile(profile)
            try:
                self._assign_payload(profile, payload)
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
        """确认目标实例没有被任何根对象引用。"""
        with self._lock:
            for owner in self._data.profiles:
                if owner is profile:
                    continue
                if owner.vision_image_profile is profile:
                    raise ValueError(
                        f"LLM profile {profile.name!r} is referenced by "
                        f"{owner.name!r}.vision_image_profile"
                    )
                if owner.audio_profile is profile:
                    raise ValueError(
                        f"LLM profile {profile.name!r} is referenced by "
                        f"{owner.name!r}.audio_profile"
                    )
                if owner.vision_video_profile is profile:
                    raise ValueError(
                        f"LLM profile {profile.name!r} is referenced by "
                        f"{owner.name!r}.vision_video_profile"
                    )
            if self._data.approval_profile is profile:
                raise ValueError(
                    f"LLM profile {profile.name!r} is the approval Profile"
                )
            if self._data.metadata_profile is profile:
                raise ValueError(
                    f"LLM profile {profile.name!r} is the metadata Profile"
                )
            if self.is_any_global_modality_profile(profile):
                raise ValueError(
                    f"LLM profile {profile.name!r} is referenced by a global modality profile"
                )

    def remove_profile(self, name: str) -> LLMProfile:
        """移除未被其他根 Profile 引用的实例。"""
        with self._lock:
            profile = self.get_profile(name)
            self.assert_removable(profile)
            index = self._data.profiles.index(profile)
            self._data.profiles.pop(index)
            try:
                self._save_unlocked()
            except Exception:
                self._data.profiles.insert(index, profile)
                raise
            logger.info("Removed LLM profile | name=%s", name)
            return profile

    # ------------------------------------------------------------------
    # 加载与迁移
    # ------------------------------------------------------------------

    def _load_unlocked(self) -> LLMProfileData:
        if not contains(LLM_PROFILES_ES_KEY, make_config(self._path)):
            return LLMProfileData()

        data = load(
            LLM_PROFILES_ES_KEY,
            make_config(self._path),
            LLMProfileData,
            ignore_missing_fields=True,
        )
        return data

    def _resolve_profile_reference(
        self,
        name: str | None,
    ) -> LLMProfile | None:
        if name is None:
            return None
        if not isinstance(name, str) or not name:
            raise ValueError("Profile reference must be a Profile name or null")
        return self.get_profile(name)

    @staticmethod
    def _snapshot_profile(profile: LLMProfile) -> LLMProfile:
        return profile.model_copy()

    @staticmethod
    def _restore_profile(profile: LLMProfile, snapshot: LLMProfile) -> None:
        profile.name = snapshot.name
        profile.llm_client_name = snapshot.llm_client_name
        profile.base_url = snapshot.base_url
        profile.model = snapshot.model
        profile.api_key = snapshot.api_key
        profile.temperature = snapshot.temperature
        profile.max_output_tokens = snapshot.max_output_tokens
        profile.reasoning_effort = snapshot.reasoning_effort
        profile.max_context_tokens = snapshot.max_context_tokens
        profile.vision_image_profile = snapshot.vision_image_profile
        profile.audio_profile = snapshot.audio_profile
        profile.vision_video_profile = snapshot.vision_video_profile
        profile.soul_file = snapshot.soul_file

    def _assign_payload(
        self,
        profile: LLMProfile,
        payload: LLMProfilePayload,
    ) -> None:
        profile.name = payload.name
        profile.llm_client_name = payload.llm_client_name
        profile.base_url = payload.base_url
        profile.model = payload.model
        profile.api_key = payload.api_key
        profile.temperature = payload.temperature
        profile.max_output_tokens = payload.max_output_tokens
        profile.reasoning_effort = payload.reasoning_effort
        profile.max_context_tokens = payload.max_context_tokens
        profile.vision_image_profile = self._resolve_profile_reference(
            payload.vision_image_profile,
        )
        profile.audio_profile = self._resolve_profile_reference(
            payload.audio_profile,
        )
        profile.vision_video_profile = self._resolve_profile_reference(
            payload.vision_video_profile,
        )
        profile.soul_file = payload.soul_file

    # ------------------------------------------------------------------
    # v2 写入
    # ------------------------------------------------------------------

    @staticmethod
    def _cleanup_easysave_backup_after_save(
        temp_path: Path,
        original_error: EasySaveBackupCleanupError,
    ) -> None:
        """清理 easysave 已提交临时文件留下的 Windows 备份。"""
        backup_path = Path(f"{temp_path}.bak")
        last_error: OSError | None = None
        for attempt in range(LLM_PROFILE_BACKUP_CLEANUP_RETRIES):
            try:
                backup_path.unlink(missing_ok=True)
                if attempt:
                    logger.info(
                        "Removed transient easysave backup after retry | path=%s attempts=%d",
                        backup_path,
                        attempt + 1,
                    )
                return
            except OSError as exc:
                last_error = exc
                if attempt + 1 < LLM_PROFILE_BACKUP_CLEANUP_RETRIES:
                    time.sleep(LLM_PROFILE_BACKUP_CLEANUP_DELAY_SECONDS)
        raise original_error from last_error

    def _save_unlocked(self, data: LLMProfileData | None = None) -> None:
        target = data if data is not None else self._data
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
            try:
                save(LLM_PROFILES_ES_KEY, make_config(temp_path), target)
            except EasySaveBackupCleanupError as exc:
                # easysave 此时已完成临时目标的原子替换；只重试 Windows
                # 对临时备份的删除，然后继续外层的最终原子替换。
                self._cleanup_easysave_backup_after_save(temp_path, exc)
            replace_atomic(temp_path, self._path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
