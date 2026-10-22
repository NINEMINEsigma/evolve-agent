"""LLM Profile v2 根对象存储。"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from easysave import load, save
from framework import AsyncSystem
from entity.typeref import make_config

from entity.constant import (
    LLM_PROFILES_ES_FILENAME,
    LLM_PROFILES_ES_KEY,
)
from entity.puretype.llm import (
    LLMProfile,
    LLMProfileData,
    LLMProfilePayload,
)
from util.atomic_io import replace_atomic
from system.context import RuntimeContext
from system.lifecycle import LifecycleFailure
from interface.llm_profile_store import ILLMProfileStore
from interface.runtime_system import IRuntimeSystem

logger = logging.getLogger(__name__)


class ProfileNotFoundError(LookupError):
    """指定名称的 LLM Profile 不存在（可预期的用户请求错误）。"""


class ProfileConflictError(ValueError):
    """LLM Profile 名称冲突或引用占用导致拒绝操作（可预期的用户请求错误）。"""


class LLMProfileStore(ILLMProfileStore):
    """进程内唯一的 ``LLMProfileData`` 根对象存储。

    注册为 framework AsyncSystem，依赖 RuntimeSystem；由 Application 在最终
    装配时经 ``get_system(ILLMProfileStore)`` 取得。本 Store 自身创建唯一的
    共享 ``threading.RLock``，所有 Profile 事务边界通过 ``locked()`` 访问同一把锁，
    不再由 Application 注入或经模块级全局暴露。

    六个写方法遵循「先准备候选数据、持久化成功再提交内存」的顺序：
    set/create/remove 使用候选根浅拷贝及独立列表，update 显式复制并重连引用图。
    持久化失败时共享对象保持不变，异常直接传播，不做回滚或重试。
    """

    def __init__(self) -> None:
        super().__init__(dependencies=(IRuntimeSystem,))
        self._agentspace_dir: Path | None = None
        self._path: Path | None = None
        self._lock = threading.RLock()
        self._data: LLMProfileData | None = None

    async def virtual_awake(self) -> None:
        """取得 RuntimeContext，确定 agentspace 路径并加载 v2 根对象。"""
        ctx: RuntimeContext = self.get_system(IRuntimeSystem).context
        self._agentspace_dir = ctx.agentspace
        self._path = self._agentspace_dir / LLM_PROFILES_ES_FILENAME
        with self._lock:
            self._data = self._load_unlocked()

    @property
    def path(self) -> Path:
        """返回 Profile 注册表路径。"""
        if self._path is None:
            raise LifecycleFailure("LLMProfileStore has not been awakened")
        return self._path

    @property
    def agentspace_dir(self) -> Path:
        """返回 Profile 文件所在的 agentspace 目录。"""
        if self._agentspace_dir is None:
            raise LifecycleFailure("LLMProfileStore has not been awakened")
        return self._agentspace_dir

    @contextmanager
    def locked(self) -> Iterator[None]:
        """暴露本 Store 唯一的共享 RLock；原 Application.profile_lock 的事务
        边界统一经此接口访问，SessionMetadataService 和审批后端使用同一把锁。"""
        with self._lock:
            yield

    @property
    def data(self) -> LLMProfileData:
        """返回共享根对象；修改必须通过本类的写接口完成。"""
        if self._data is None:
            raise LifecycleFailure("LLMProfileStore has not been awakened")
        return self._data

    def get_data(self) -> LLMProfileData:
        """返回共享根对象；修改必须通过本类的写接口完成。"""
        with self._lock:
            return self.data

    def get_approval_profile(self) -> LLMProfile | None:
        """返回根对象当前指向的审批 Profile 实例。"""
        with self._lock:
            return self.data.approval_profile

    def set_approval_profile(self, profile: LLMProfile | None) -> None:
        """设置根对象审批 Profile 引用并持久化。"""
        with self._lock:
            if profile is not None and not any(
                candidate is profile for candidate in self.data.profiles
            ):
                raise ValueError(
                    "LLMProfileData.approval_profile must reference a profile in profiles"
                )
            candidate = self.data.model_copy()
            candidate.approval_profile = profile
            self._save_unlocked(candidate)
            self.data.approval_profile = profile

    def is_approval_profile(self, profile: LLMProfile) -> bool:
        """返回 Profile 是否是根对象当前的审批 Profile 实例。"""
        with self._lock:
            return self.data.approval_profile is profile

    def get_metadata_profile(self) -> LLMProfile | None:
        """返回根对象当前指向的全局元数据 Profile 实例。"""
        with self._lock:
            return self.data.metadata_profile

    def set_metadata_profile(self, profile: LLMProfile | None) -> None:
        """设置根对象全局元数据 Profile 引用并持久化。"""
        with self._lock:
            if profile is not None and not any(
                candidate is profile for candidate in self.data.profiles
            ):
                raise ValueError(
                    "LLMProfileData.metadata_profile must reference a profile in profiles"
                )
            candidate = self.data.model_copy()
            candidate.metadata_profile = profile
            self._save_unlocked(candidate)
            self.data.metadata_profile = profile

    def is_metadata_profile(self, profile: LLMProfile) -> bool:
        """返回 Profile 是否是根对象当前的全局元数据 Profile 实例。"""
        with self._lock:
            return self.data.metadata_profile is profile

    def get_toolchain_summary_profile(self) -> LLMProfile | None:
        """返回根对象当前指向的工具链摘要 Profile 实例。"""
        with self._lock:
            return self.data.toolchain_summary_profile

    def set_toolchain_summary_profile(self, profile: LLMProfile | None) -> None:
        """设置根对象工具链摘要 Profile 引用并持久化。"""
        with self._lock:
            if profile is not None and not any(
                candidate is profile for candidate in self.data.profiles
            ):
                raise ValueError(
                    "LLMProfileData.toolchain_summary_profile must reference a profile in profiles"
                )
            candidate = self.data.model_copy()
            candidate.toolchain_summary_profile = profile
            self._save_unlocked(candidate)
            self.data.toolchain_summary_profile = profile

    def is_toolchain_summary_profile(self, profile: LLMProfile) -> bool:
        """返回 Profile 是否是根对象当前的工具链摘要 Profile 实例。"""
        with self._lock:
            return self.data.toolchain_summary_profile is profile

    def get_global_modality_profile(
        self,
        media_type: Literal["image", "audio", "video"],
    ) -> LLMProfile | None:
        """返回指定媒体类型的全局回退 Profile 实例。"""
        with self._lock:
            if media_type == "image":
                return self.data.global_vision_image_profile
            if media_type == "audio":
                return self.data.global_audio_profile
            if media_type == "video":
                return self.data.global_vision_video_profile
            raise ValueError(f"Unsupported modality type: {media_type!r}")

    def set_global_modality_profile(
        self,
        media_type: Literal["image", "audio", "video"],
        profile: LLMProfile | None
        ) -> None:
        """设置指定媒体类型的全局回退 Profile 引用并持久化。"""
        with self._lock:
            if profile is not None and not any(
                candidate is profile for candidate in self.data.profiles
            ):
                raise ValueError(
                    f"LLMProfileData global {media_type} profile must reference "
                    "a profile in profiles"
                )
            candidate = self.data.model_copy()
            if media_type == "image":
                candidate.global_vision_image_profile = profile
            elif media_type == "audio":
                candidate.global_audio_profile = profile
            elif media_type == "video":
                candidate.global_vision_video_profile = profile
            else:
                raise ValueError(f"Unsupported modality type: {media_type!r}")
            self._save_unlocked(candidate)
            if media_type == "image":
                self.data.global_vision_image_profile = profile
            elif media_type == "audio":
                self.data.global_audio_profile = profile
            else:
                self.data.global_vision_video_profile = profile

    def is_global_modality_profile(
        self,
        profile: LLMProfile,
        media_type: Literal["image", "audio", "video"]
        ) -> bool:
        """返回 Profile 是否是指定媒体类型的全局回退 Profile。"""
        return self.get_global_modality_profile(media_type) is profile

    def is_any_global_modality_profile(self, profile: LLMProfile) -> bool:
        """返回 Profile 是否被任一全局多模态引用指向。"""
        with self._lock:
            return (
                self.data.global_vision_image_profile is profile
                or self.data.global_audio_profile is profile
                or self.data.global_vision_video_profile is profile
            )

    def list_profiles(self) -> list[LLMProfile]:
        """返回根列表的浅拷贝，列表元素仍是根对象中的实例。"""
        with self._lock:
            return list(self.data.profiles)

    def snapshot_profile(self, profile: LLMProfile) -> LLMProfile:
        """返回根对象中指定 Profile 的调用时深快照。"""
        with self._lock:
            if not any(candidate is profile for candidate in self.data.profiles):
                raise ValueError(
                    "Active LLM Profile does not belong to the current LLM Profile root"
                )
            return profile.model_copy(deep=True)

    def get_profile(self, name: str) -> LLMProfile:
        """按名称返回根对象中的 Profile；未命中抛出 ``ProfileNotFoundError``。"""
        with self._lock:
            for profile in self.data.profiles:
                if profile.name == name:
                    return profile
        raise ProfileNotFoundError(f"LLM profile not found: {name!r}")

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
                raise ProfileConflictError("LLM profile name must not be empty")
            if any(p.name == payload.name for p in self.data.profiles):
                raise ProfileConflictError(
                    f"Duplicate LLM profile name: {payload.name!r}"
                )
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
            candidate = self.data.model_copy()
            candidate.profiles = self.data.profiles + [profile]
            self._save_unlocked(candidate)
            self.data.profiles.append(profile)
            logger.info("Created LLM profile | name=%s", profile.name)
            return profile

    def update_profile(
        self,
        original_name: str,
        payload: LLMProfilePayload
        ) -> LLMProfile:
        """原地更新 Profile；重命名不会替换实例身份。"""
        with self._lock:
            profile = self.get_profile(original_name)
            if not payload.name:
                raise ProfileConflictError("LLM profile name must not be empty")
            if any(
                other is not profile and other.name == payload.name
                for other in self.data.profiles
            ):
                raise ProfileConflictError(
                    f"Duplicate LLM profile name: {payload.name!r}"
                )
            # 两阶段复制并重连引用，候选图内自引用/循环引用保持对象身份。
            candidate = self._copy_root_graph()
            candidate_profile = next(
                p for p in candidate.profiles if p.name == original_name
            )
            self._assign_payload_in(
                candidate_profile,
                payload,
                candidate.profiles,
            )
            # 保存前在原图预解析引用，使提交阶段只剩纯赋值，避免保存后查找再失败。
            orig_vision_image = self._resolve_profile_reference_in(
                payload.vision_image_profile, self.data.profiles,
            )
            orig_audio = self._resolve_profile_reference_in(
                payload.audio_profile, self.data.profiles,
            )
            orig_vision_video = self._resolve_profile_reference_in(
                payload.vision_video_profile, self.data.profiles,
            )
            self._save_unlocked(candidate)
            # 提交到原实例：用原图已解析的引用，绝不把副本引用放进原图。
            self._apply_profile_fields(
                profile,
                payload,
                vision_image_profile=orig_vision_image,
                audio_profile=orig_audio,
                vision_video_profile=orig_vision_video,
            )
            logger.info(
                "Updated LLM profile | old_name=%s new_name=%s",
                original_name,
                profile.name,
            )
            return profile

    def assert_removable(
        self,
        profile: LLMProfile,
        *,
        clear_global_selections: bool = False
        ) -> None:
        """确认目标实例没有被任何根对象引用。

        ``clear_global_selections=True`` 时仅忽略审批 Profile、全局元数据
        Profile 与工具链摘要 Profile 三个全局引用的删除检查；其他 Profile 的
        多模态引用与三路全局多模态回退引用仍会阻止删除。默认检查全部引用。
        """
        with self._lock:
            for owner in self.data.profiles:
                if owner is profile:
                    continue
                if owner.vision_image_profile is profile:
                    raise ProfileConflictError(
                        f"LLM profile {profile.name!r} is referenced by "
                        f"{owner.name!r}.vision_image_profile"
                    )
                if owner.audio_profile is profile:
                    raise ProfileConflictError(
                        f"LLM profile {profile.name!r} is referenced by "
                        f"{owner.name!r}.audio_profile"
                    )
                if owner.vision_video_profile is profile:
                    raise ProfileConflictError(
                        f"LLM profile {profile.name!r} is referenced by "
                        f"{owner.name!r}.vision_video_profile"
                    )
            if self.is_any_global_modality_profile(profile):
                raise ProfileConflictError(
                    f"LLM profile {profile.name!r} is referenced by a global modality profile"
                )
            if not clear_global_selections:
                if self.data.approval_profile is profile:
                    raise ProfileConflictError(
                        f"LLM profile {profile.name!r} is the approval Profile"
                    )
                if self.data.metadata_profile is profile:
                    raise ProfileConflictError(
                        f"LLM profile {profile.name!r} is the metadata Profile"
                    )
                if self.data.toolchain_summary_profile is profile:
                    raise ProfileConflictError(
                        f"LLM profile {profile.name!r} is the toolchain summary Profile"
                    )

    def remove_profile(
        self,
        name: str,
        *,
        clear_global_selections: bool = False
        ) -> LLMProfile:
        """移除未被其他根 Profile 引用的实例。

        ``clear_global_selections=True`` 时，在一次 Profile 文件保存中删除
        Profile 并清空指向它的审批 Profile、全局元数据 Profile 与工具链摘要
        Profile 引用；默认行为仍要求这些引用为空才允许删除。
        """
        with self._lock:
            profile = self.get_profile(name)
            self.assert_removable(
                profile,
                clear_global_selections=clear_global_selections,
            )
            index = next(
                i for i, member in enumerate(self.data.profiles) if member is profile
            )
            remaining = [p for p in self.data.profiles if p is not profile]
            candidate = self.data.model_copy()
            candidate.profiles = remaining
            if clear_global_selections:
                if self.data.approval_profile is profile:
                    candidate.approval_profile = None
                if self.data.metadata_profile is profile:
                    candidate.metadata_profile = None
                if self.data.toolchain_summary_profile is profile:
                    candidate.toolchain_summary_profile = None
            self._save_unlocked(candidate)
            self.data.profiles.pop(index)
            if clear_global_selections:
                if self.data.approval_profile is profile:
                    self.data.approval_profile = None
                if self.data.metadata_profile is profile:
                    self.data.metadata_profile = None
                if self.data.toolchain_summary_profile is profile:
                    self.data.toolchain_summary_profile = None
            logger.info("Removed LLM profile | name=%s", name)
            return profile

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------

    def _load_unlocked(self) -> LLMProfileData:
        # 文件不存在时允许初始化空根；已有文件缺 v2 key 让 load 失败。
        path = self.path
        if not path.exists():
            return LLMProfileData()

        return load(
            LLM_PROFILES_ES_KEY,
            make_config(path),
            LLMProfileData,
            ignore_missing_fields=True,
        )

    def _copy_root_graph(self) -> LLMProfileData:
        """先复制全部 Profile，再按身份重连引用，避免循环图被递归展开。"""
        copies = {id(profile): profile.model_copy() for profile in self.data.profiles}

        def copied(profile: LLMProfile | None) -> LLMProfile | None:
            return None if profile is None else copies[id(profile)]

        for original in self.data.profiles:
            clone = copies[id(original)]
            clone.vision_image_profile = copied(original.vision_image_profile)
            clone.audio_profile = copied(original.audio_profile)
            clone.vision_video_profile = copied(original.vision_video_profile)
        candidate = self.data.model_copy()
        candidate.profiles = [copies[id(profile)] for profile in self.data.profiles]
        candidate.approval_profile = copied(self.data.approval_profile)
        candidate.metadata_profile = copied(self.data.metadata_profile)
        candidate.toolchain_summary_profile = copied(self.data.toolchain_summary_profile)
        candidate.global_vision_image_profile = copied(self.data.global_vision_image_profile)
        candidate.global_audio_profile = copied(self.data.global_audio_profile)
        candidate.global_vision_video_profile = copied(self.data.global_vision_video_profile)
        return candidate

    def _resolve_profile_reference(
        self,
        name: str | None,
    ) -> LLMProfile | None:
        return self._resolve_profile_reference_in(name, self.data.profiles)

    @staticmethod
    def _resolve_profile_reference_in(
        name: str | None,
        profiles: list[LLMProfile],
    ) -> LLMProfile | None:
        if name is None:
            return None
        if not name:
            raise ProfileConflictError("Profile reference name must not be empty")
        for candidate in profiles:
            if candidate.name == name:
                return candidate
        raise ProfileNotFoundError(f"LLM profile not found: {name!r}")

    @staticmethod
    def _assign_payload_in(
        profile: LLMProfile,
        payload: LLMProfilePayload,
        profiles: list[LLMProfile]
        ) -> None:
        # 在指定列表内解析引用并立即赋值；用于候选图的验证性赋值。
        LLMProfileStore._apply_profile_fields(
            profile,
            payload,
            vision_image_profile=LLMProfileStore._resolve_profile_reference_in(
                payload.vision_image_profile, profiles,
            ),
            audio_profile=LLMProfileStore._resolve_profile_reference_in(
                payload.audio_profile, profiles,
            ),
            vision_video_profile=LLMProfileStore._resolve_profile_reference_in(
                payload.vision_video_profile, profiles,
            ),
        )

    @staticmethod
    def _apply_profile_fields(
        profile: LLMProfile,
        payload: LLMProfilePayload,
        *,
        vision_image_profile: LLMProfile | None,
        audio_profile: LLMProfile | None,
        vision_video_profile: LLMProfile | None
        ) -> None:
        """用已解析的引用与标量字段赋值到目标 Profile 实例。

        不再做任何名称查找；调用方负责在赋值前完成引用解析。
        """
        profile.name = payload.name
        profile.llm_client_name = payload.llm_client_name
        profile.base_url = payload.base_url
        profile.model = payload.model
        profile.api_key = payload.api_key
        profile.temperature = payload.temperature
        profile.max_output_tokens = payload.max_output_tokens
        profile.reasoning_effort = payload.reasoning_effort
        profile.max_context_tokens = payload.max_context_tokens
        profile.vision_image_profile = vision_image_profile
        profile.audio_profile = audio_profile
        profile.vision_video_profile = vision_video_profile
        profile.soul_file = payload.soul_file

    # ------------------------------------------------------------------
    # v2 写入
    # ------------------------------------------------------------------

    def _save_unlocked(self, target: LLMProfileData) -> None:
        agentspace_dir = self.agentspace_dir
        path = self.path
        agentspace_dir.mkdir(parents=True, exist_ok=True)

        if path.exists():
            original = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(original, dict):
                raise TypeError("LLM profile storage file must contain a JSON object")
        else:
            original = {}

        fd, temp_name = tempfile.mkstemp(
            prefix=f"{path.name}.",
            suffix=".tmp",
            dir=str(agentspace_dir),
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
            # 外层临时文件 + 原子替换避免 easysave 提交后清理错误导致真实目标半提交。
            save(LLM_PROFILES_ES_KEY, make_config(temp_path), target)
            replace_atomic(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
