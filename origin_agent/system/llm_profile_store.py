"""LLM profiles 持久化存储。

封装两类存储：

1. **agentspace 全局 profiles 列表**（`llm_profiles.es`，easysave 序列化）：
   前端 GET/PUT 的唯一权威数据源，平铺 ``list[LlmProfile]``。
2. **会话级 / 全局 profile 快照**（JSON，经 ``atomic_io`` 原子写）：
   用于隐式触发源（cron/auto-title/summary/fallback）的最近使用 profile 回落。

快照文件存完整 ``LlmProfile``（而非仅 name），抗 profile 改名/删除。
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from easysave import save, load, contains

from entity.puretype.llm import LLMProfile
from entity.constant import (
    LLM_PROFILES_ES_FILENAME,
    LLM_PROFILES_ES_KEY,
)
from system.atomic_io import write_text_atomic

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# agentspace 全局 profiles 列表（easysave）
# ---------------------------------------------------------------------------

def _es_path(agentspace_dir: Path) -> Path:
    """返回 agentspace 下的 profiles easysave 文件路径。"""
    return Path(agentspace_dir) / LLM_PROFILES_ES_FILENAME


def _ensure_uid(profile: LLMProfile) -> LLMProfile:
    """若 profile 无 uid 则生成并返回新实例（函数式无副作用）。

    返回带 uid 的 LLMProfile；若原已有 uid 则原样返回。
    uid 由后端 uuid4().hex 生成，32 字符无连字符，不可更改。
    """
    if profile.uid:
        return profile
    return profile.model_copy(update={"uid": uuid.uuid4().hex})


def _validate_references(profiles: list[LLMProfile]) -> None:
    """校验三个引用字段：悬空、自引用、循环引用。违规 raise ValueError。

    - 悬空：引用的 uid 不在列表中
    - 自引用：vision_image_profile/audio_profile/vision_video_profile == self.uid
    - 循环：沿单一引用字段链检测（A.vision→B.vision→A），跨字段不视为循环
    """
    uid_set = {p.uid for p in profiles}
    for p in profiles:
        for field in ("vision_image_profile", "audio_profile", "vision_video_profile"):
            ref = getattr(p, field)
            if not ref:
                continue
            if ref not in uid_set:
                raise ValueError(
                    f"Profile {p.name!r} {field} references non-existent uid {ref!r}"
                )
            if ref == p.uid:
                raise ValueError(
                    f"Profile {p.name!r} {field} cannot reference itself"
                )
    # 循环检测：沿单一字段链遍历，遇回到起点则循环
    by_uid = {p.uid: p for p in profiles if p.uid}
    for start in profiles:
        if not start.uid:
            continue
        for field in ("vision_image_profile", "audio_profile", "vision_video_profile"):
            visited: set[str] = set()
            current = start
            while True:
                ref = getattr(current, field)
                if not ref or ref not in by_uid:
                    break
                if ref == start.uid and visited:
                    raise ValueError(
                        f"Circular reference detected: profile {start.name!r} .{field} → ... → self"
                    )
                if ref in visited:
                    break  # 其他环，非从 start 开始，不报错
                visited.add(ref)
                current = by_uid[ref]


def load_profiles(agentspace_dir: Path) -> list[LLMProfile]:
    """从 agentspace 读取全部 LLM profiles。

    文件缺失或 key 不存在时返回空列表（不报错）。
    easysave 已对 list[LLMProfile] 保留类型，故新格式条目直接复用类型实例；
    旧格式（平铺 dict）条目则经 model_validate 还原，保证向后兼容。

    旧 profile 无 uid 时自动补 uuid4().hex 并立即固化（迁移副作用仅一次）。
    """
    path = _es_path(agentspace_dir)
    try:
        raw = load(LLM_PROFILES_ES_KEY, str(path))
    except FileNotFoundError:
        return []
    except KeyError:
        return []
    if not isinstance(raw, list):
        logger.warning("LLM profiles in %s is not a list: %s", path, type(raw))
        return []
    profiles: list[LLMProfile] = []
    migrated = False
    for item in raw:
        if isinstance(item, LLMProfile):
            if not item.uid:
                item = _ensure_uid(item)
                migrated = True
            profiles.append(item)
            continue
        try:
            p = LLMProfile.model_validate(item)
            if not p.uid:
                p = _ensure_uid(p)
                migrated = True
            profiles.append(p)
        except Exception:
            logger.warning("Skipping invalid LLM profile entry in %s: %s", path, item, exc_info=True)
    if migrated and profiles:
        try:
            save_profiles(agentspace_dir, profiles)
            logger.info(
                "Migrated LLM profiles with new uid in %s (%d profiles)",
                path, sum(1 for p in profiles if p.uid),
            )
        except Exception:
            logger.warning("Failed to persist uid migration in %s", path, exc_info=True)
    logger.info("Loaded %d LLM profiles from %s", len(profiles), path)
    return profiles


def save_profiles(agentspace_dir: Path, profiles: list[LLMProfile]) -> None:
    """将全部 LLM profiles 原子写入 agentspace。

    先校验列表内 name 唯一（重名 → ValueError），再经 easysave 直接存 list[LLMProfile]，
    由 easysave 保留类型信息（type_token 记录 entity.puretype.llm.LLMProfile），
    不再额外 model_dump() 降级为 dict。

    校验 name 唯一、uid 唯一、引用字段（悬空/自引用/循环）。
    """
    names: set[str] = set()
    uids: set[str] = set()
    for p in profiles:
        if p.name in names:
            raise ValueError(f"Duplicate LLM profile name: {p.name!r}")
        names.add(p.name)
        if p.uid:
            if p.uid in uids:
                raise ValueError(f"Duplicate LLM profile uid: {p.uid!r}")
            uids.add(p.uid)
    _validate_references(profiles)
    path = _es_path(agentspace_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    save(LLM_PROFILES_ES_KEY, str(path), profiles)
    logger.info("Saved %d LLM profiles to %s", len(profiles), path)


# ---------------------------------------------------------------------------
# profile 快照（JSON，原子写）— 会话级 / 全局指针
# ---------------------------------------------------------------------------

def read_profile_snapshot(path: Path) -> LLMProfile | None:
    """读取单个 profile 快照 JSON 文件。

    文件缺失或解析失败时返回 None。
    """
    p = Path(path)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return LLMProfile.model_validate(data)
    except Exception:
        logger.warning("Failed to read profile snapshot %s", p, exc_info=True)
        return None


def write_profile_snapshot(path: Path, profile: LLMProfile) -> None:
    """原子写入单个 profile 快照 JSON 文件。"""
    payload = profile.model_dump_json(indent=2)
    write_text_atomic(Path(path), payload)