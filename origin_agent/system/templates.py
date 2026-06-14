"""统一模板读取工具。"""

from __future__ import annotations

import logging
from pathlib import Path

from system.pathutils import get_templates_dir

logger = logging.getLogger(__name__)


def select_template_root(lang: str = "zh") -> Path:
    """根据语言选择模板根目录。"""
    templates = get_templates_dir()
    if lang == "zh":
        zh_dir = templates / "zh"
        if zh_dir.is_dir():
            return zh_dir
    return templates


def read_template_path(name: str, lang: str = "zh") -> Path:
    """返回模板路径；语言目录缺失时回退到默认模板目录。"""
    root = select_template_root(lang)
    candidate = root / name
    if candidate.is_file():
        return candidate
    return get_templates_dir() / name


def read_template(name: str, lang: str = "zh") -> str:
    """读取模板文本，缺失或读取失败时返回空字符串。"""
    path = read_template_path(name, lang)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning("Failed to read template %s: %s", path, exc)
        return ""