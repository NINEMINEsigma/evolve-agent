"""统一模板读取工具。"""

from __future__ import annotations

import logging
from pathlib import Path

from system.pathutils import get_templates_dir

logger = logging.getLogger(__name__)


def select_template_root() -> Path:
    """返回模板根目录。"""
    return get_templates_dir()


def read_template_path(name: str) -> Path:
    """返回模板文件路径。"""
    return get_templates_dir() / name


def read_template(name: str) -> str:
    """读取模板文本，缺失或读取失败时返回空字符串。"""
    path = read_template_path(name)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning("Failed to read template %s: %s", path, exc)
        return ""