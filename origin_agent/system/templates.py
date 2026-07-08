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


def render_multi_agent_prompt(template: str, character_name: str) -> str:
    """渲染多 Agent 系统提示词模板，注入角色名与路由常量。

    模板中可用占位符：
    - {{CHARACTER_NAME}}: 当前 Agent 角色名
    - {{TAG_VISIBLE}}: MULTI_AGENT_ROUTING_TAG_VISIBLE
    - {{TAG_RESPONSE}}: MULTI_AGENT_ROUTING_TAG_RESPONSE
    - {{ALL_AGENTS}}: ALL_AGENTS_CHARACTER_REF_NAME
    - {{RESPONSE_NONE}}: MULTI_AGENT_ROUTING_RESPONSE_NONE
    """
    from entity.constant import (
        ALL_AGENTS_CHARACTER_REF_NAME,
        MULTI_AGENT_ROUTING_RESPONSE_NONE,
        MULTI_AGENT_ROUTING_TAG_RESPONSE,
        MULTI_AGENT_ROUTING_TAG_VISIBLE,
    )

    return (
        template.replace("{{CHARACTER_NAME}}", character_name)
        .replace("{{TAG_VISIBLE}}", MULTI_AGENT_ROUTING_TAG_VISIBLE)
        .replace("{{TAG_RESPONSE}}", MULTI_AGENT_ROUTING_TAG_RESPONSE)
        .replace("{{ALL_AGENTS}}", ALL_AGENTS_CHARACTER_REF_NAME)
        .replace("{{RESPONSE_NONE}}", MULTI_AGENT_ROUTING_RESPONSE_NONE)
    )