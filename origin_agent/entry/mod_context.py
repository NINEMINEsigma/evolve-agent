"""Pure, invocation-local preparation of keyword-triggered mod fixators."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from abstract.mods.loader import match_mod_keywords, read_mod_documents, resolve_related_names
from abstract.mods.render import render_mod_document
from entity.constant import MOD_MAX_RENDERED_BYTES
from entity.error import ModBudgetExceededError
from entity.messages import BaseMessage, ModTextBlock, TextBlock, ToolResultMessage
from entity.puretype import ModCatalog, ModRenderContext, Role
from entity.puretype_after import ModMessageReplacement


def user_message_texts(message: BaseMessage) -> tuple[str, ...]:
    if message.role != Role.USER:
        return ()
    content = message.content
    if isinstance(content, str):
        return (content,)
    if isinstance(content, dict):
        return (json.dumps(content, ensure_ascii=False, sort_keys=True),)
    return tuple(block.text for block in content
                 if isinstance(block, TextBlock) and not isinstance(block, ModTextBlock))


def collect_visible_mod_names(
    messages: Sequence[BaseMessage],
    *,
    character_name: str,
    resource_session_id: str,
) -> set[str]:
    names: set[str] = set()
    for message in messages:
        if not message.is_visible_to(character_name):
            continue
        blocks = list(message.mod_fixators)
        if isinstance(message, ToolResultMessage):
            blocks.extend(block for block in message.result_text_blocks if isinstance(block, ModTextBlock))
        names.update(block.mod_name for block in blocks
                     if block.resource_session_id == resource_session_id
                     and block.is_visible_to(character_name))
    return names


def prepare_mod_replacements(
    messages: Sequence[BaseMessage],
    *,
    root: Path,
    catalog: ModCatalog,
    render_context: ModRenderContext,
    characters: Sequence[str],
) -> tuple[ModMessageReplacement, ...]:
    pending = [(index, message) for index, message in enumerate(messages)
               if message.role == Role.USER and not message.mod_keywords_processed]
    existing = {character: collect_visible_mod_names(
        messages, character_name=character, resource_session_id=render_context.resource_session_id,
    ) for character in dict.fromkeys(characters)}
    orders: dict[int, tuple[str, ...]] = {}
    needed: dict[str, None] = {}
    for index, message in pending:
        roots = match_mod_keywords(catalog, user_message_texts(message))
        order = resolve_related_names(catalog, roots) if roots else ()
        orders[index] = order
        for name in order:
            if any(message.is_visible_to(character) and name not in names
                   for character, names in existing.items()):
                needed[name] = None
    # 一次读取全部真正可能新增的正文；同名跨消息不重复读，原始字节统一计量。
    documents = read_mod_documents(root, catalog, tuple(needed)) if needed else ()
    rendered = {document.metadata.name: render_mod_document(document, render_context)
                for document in documents}
    replacements: list[ModMessageReplacement] = []
    encoded_bytes = 0
    for index, message in pending:
        blocks = list(message.mod_fixators)
        for name in orders[index]:
            audience = tuple(character for character, names in existing.items()
                             if message.is_visible_to(character) and name not in names)
            if not audience:
                continue
            block = ModTextBlock(
                text=rendered[name], mod_name=name,
                resource_session_id=render_context.resource_session_id,
                visible_characters=audience,
            )
            encoded_bytes += len(json.dumps(block.as_fixator_text(), ensure_ascii=False).encode("utf-8"))
            if encoded_bytes > MOD_MAX_RENDERED_BYTES:
                raise ModBudgetExceededError("New mod fixators exceed the encoded content budget")
            blocks.append(block)
            for character in audience:
                existing[character].add(name)
        replacement = message.model_copy(update={"mod_fixators": blocks, "mod_keywords_processed": True})
        replacements.append(ModMessageReplacement(index=index, original=message, replacement=replacement))
    return tuple(replacements)
