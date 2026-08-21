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


def load_profiles(agentspace_dir: Path) -> list[LLMProfile]:
    """从 agentspace 读取全部 LLM profiles。

    文件缺失或 key 不存在时返回空列表（不报错）。
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
    for item in raw:
        try:
            profiles.append(LLMProfile.model_validate(item))
        except Exception:
            logger.warning("Skipping invalid LLM profile entry in %s: %s", path, item, exc_info=True)
    return profiles


def save_profiles(agentspace_dir: Path, profiles: list[LLMProfile]) -> None:
    """将全部 LLM profiles 原子写入 agentspace。

    先校验列表内 name 唯一（重名 → ValueError），再经 easysave 存平铺 dict 列表。
    """
    names: set[str] = set()
    for p in profiles:
        if p.name in names:
            raise ValueError(f"Duplicate LLM profile name: {p.name!r}")
        names.add(p.name)
    path = _es_path(agentspace_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [p.model_dump() for p in profiles]
    save(LLM_PROFILES_ES_KEY, str(path), payload)


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