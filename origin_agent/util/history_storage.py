"""Shared, version-aware History reading without application initialization."""

from __future__ import annotations

import re
from collections.abc import Collection
from pathlib import Path

from easysave import contains, load

from entity.constant import (
    History_Version, LEGACY_HISTORY_VERSION, MOD_NAME_PATTERN, ALL_AGENTS_CHARACTER_REF_NAME,
)
from entity.puretype import Role
from entity.messages import BaseMessage, History, ModTextBlock, TextBlock, ToolResultMessage
from entity.typeref import make_config


def select_history_key(available_keys: Collection[str]) -> str:
    if History_Version in available_keys:
        return History_Version
    if LEGACY_HISTORY_VERSION in available_keys:
        return LEGACY_HISTORY_VERSION
    raise ValueError("History file has no supported version key")


def _validate_mod_block(block: ModTextBlock) -> None:
    if not isinstance(block.mod_name, str) or re.fullmatch(MOD_NAME_PATTERN, block.mod_name) is None:
        raise ValueError("Invalid persisted mod name")
    if not isinstance(block.resource_session_id, str) or not block.resource_session_id.strip():
        raise ValueError("Invalid persisted mod resource owner")
    if not isinstance(block.text, str) or not block.text.strip():
        raise ValueError("Invalid persisted mod body")
    audience = block.visible_characters
    if (not isinstance(audience, tuple) or not audience
            or any(not isinstance(name, str) or not name.strip() for name in audience)
            or ALL_AGENTS_CHARACTER_REF_NAME in audience
            or len(set(audience)) != len(audience)):
        raise ValueError("Invalid persisted mod audience")


def normalize_loaded_history(history: History, stored_key: str) -> History:
    if stored_key not in (History_Version, LEGACY_HISTORY_VERSION):
        raise ValueError(f"Unsupported History key: {stored_key}")
    if not isinstance(history, History) or not isinstance(history.messages, list):
        raise TypeError("Stored root must be a History with a message list")
    for message in history.messages:
        if not isinstance(message, BaseMessage):
            raise TypeError("Invalid persisted History message")
        if stored_key == LEGACY_HISTORY_VERSION:
            message.mod_fixators = []
            message.mod_keywords_processed = True
            if isinstance(message, ToolResultMessage):
                message.result_text_blocks = []
        if type(message.mod_keywords_processed) is not bool or not isinstance(message.mod_fixators, list):
            raise TypeError("Invalid persisted mod processing fields")
        if message.mod_fixators and message.role != Role.USER:
            raise ValueError("Only formal user messages may carry mod fixators")
        for block in message.mod_fixators:
            if not isinstance(block, ModTextBlock):
                raise TypeError("Invalid persisted mod fixator type")
            _validate_mod_block(block)
        if isinstance(message, ToolResultMessage):
            if not isinstance(message.result_text_blocks, list):
                raise TypeError("Invalid persisted tool text blocks")
            for block in message.result_text_blocks:
                if not isinstance(block, TextBlock) or not isinstance(block.text, str):
                    raise TypeError("Invalid persisted tool text block")
                if isinstance(block, ModTextBlock):
                    _validate_mod_block(block)
    return history


def load_history_file(path: Path) -> History:
    if not path.exists():
        raise FileNotFoundError(f"History file not found: {path}")
    config = make_config(path)
    keys = [key for key in (History_Version, LEGACY_HISTORY_VERSION) if contains(key, config)]
    selected = select_history_key(keys)
    history = load(
        selected, config, History,
        ignore_missing_fields=selected == LEGACY_HISTORY_VERSION,
    )
    return normalize_loaded_history(history, selected)
