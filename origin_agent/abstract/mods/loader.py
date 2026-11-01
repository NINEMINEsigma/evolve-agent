"""Read bounded local documents without executing their contents."""

from __future__ import annotations

import re
import stat
import sys
from collections.abc import Sequence
from pathlib import Path

from entity.constant import (
    MOD_DOCUMENT_FILENAME, MOD_METADATA_FILENAME, MOD_NAME_PATTERN,
    MOD_META_DESCRIPTION, MOD_META_RELATED, MOD_META_KEYWORDS,
    MOD_MAX_COUNT, MOD_MAX_RELATED, MOD_MAX_KEYWORDS,
    MOD_MAX_KEYWORD_CHARS, MOD_MAX_DESCRIPTION_CHARS, MOD_MAX_META_BYTES,
    MOD_MAX_TOTAL_META_BYTES, MOD_MAX_DOCUMENT_BYTES, MOD_MAX_BATCH_SOURCE_BYTES,
)
from entity.error import (
    ModConfigurationError, ModRequestError, ModBudgetExceededError,
    ModSourceChangedError,
)
from entity.puretype import ModCatalog, ModDocument, ModMetadata
from util.file_metadata import parse_meta_content


def _require_kind(path: Path, *, directory: bool) -> None:
    info = path.lstat()
    reparse = sys.platform == "win32" and bool(
        info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )
    if stat.S_ISLNK(info.st_mode) or reparse:
        raise ModConfigurationError(f"Linked mod path is not supported: {path}")
    valid = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not valid:
        raise ModConfigurationError(f"Invalid mod path type: {path}")


def _identity(path: Path) -> tuple[int, int, int, int, int]:
    info = path.stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read_bounded(path: Path, maximum: int) -> tuple[str, int]:
    _require_kind(path, directory=False)
    before = _identity(path)
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    _require_kind(path, directory=False)
    if _identity(path) != before:
        raise ModSourceChangedError(f"Mod source changed while reading: {path}")
    if len(raw) > maximum:
        raise ModBudgetExceededError(f"Mod file exceeds {maximum} bytes: {path}")
    return raw.decode("utf-8-sig"), len(raw)


def _lines(value: str, maximum: int, name: str, key: str) -> tuple[str, ...]:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if len(lines) > maximum:
        raise ModBudgetExceededError(f"Too many {key} declarations in {name}")
    return tuple(dict.fromkeys(lines))


def discover_mods(root: Path) -> ModCatalog:
    try:
        root.lstat()
    except FileNotFoundError:
        return ModCatalog()
    _require_kind(root, directory=True)
    entries: list[ModMetadata] = []
    identities: set[str] = set()
    total_bytes = 0
    for directory in sorted(root.iterdir(), key=lambda path: path.name):
        if directory.name.startswith(".") or not directory.is_dir():
            continue
        document = directory / MOD_DOCUMENT_FILENAME
        metadata = directory / MOD_METADATA_FILENAME
        declared = any(path.exists() or path.is_symlink() for path in (document, metadata))
        if not declared:
            continue
        _require_kind(directory, directory=True)
        name = directory.name
        if re.fullmatch(MOD_NAME_PATTERN, name) is None:
            raise ModConfigurationError(f"Invalid mod name: {name}", name)
        if name.casefold() in identities:
            raise ModConfigurationError(f"Case-insensitive mod name conflict: {name}", name)
        identities.add(name.casefold())
        if len(identities) > MOD_MAX_COUNT:
            raise ModBudgetExceededError(f"Mod catalog exceeds {MOD_MAX_COUNT} entries")
        _require_kind(document, directory=False)
        content, size = _read_bounded(metadata, MOD_MAX_META_BYTES)
        total_bytes += size
        if total_bytes > MOD_MAX_TOTAL_META_BYTES:
            raise ModBudgetExceededError("Mod catalog metadata exceeds its byte budget")
        values = parse_meta_content(content)
        unknown = values.keys() - {MOD_META_DESCRIPTION, MOD_META_RELATED, MOD_META_KEYWORDS}
        if unknown:
            raise ModConfigurationError(f"Unknown metadata keys in {name}: {sorted(unknown)}", name)
        description = values.get(MOD_META_DESCRIPTION, "").strip()
        if (not description or len(description.splitlines()) != 1
                or len(description) > MOD_MAX_DESCRIPTION_CHARS):
            raise ModConfigurationError(f"Invalid single-line description in {name}", name)
        related = _lines(values.get(MOD_META_RELATED, ""), MOD_MAX_RELATED, name, MOD_META_RELATED)
        keywords = _lines(values.get(MOD_META_KEYWORDS, ""), MOD_MAX_KEYWORDS, name, MOD_META_KEYWORDS)
        for target in related:
            if re.fullmatch(MOD_NAME_PATTERN, target) is None:
                raise ModConfigurationError(f"Invalid related name in {name}: {target}", name)
        if any(len(keyword) > MOD_MAX_KEYWORD_CHARS for keyword in keywords):
            raise ModConfigurationError(f"Keyword exceeds character limit in {name}", name)
        entries.append(ModMetadata(name=name, description=description, related=related, keywords=keywords))
    names = {entry.name for entry in entries}
    for entry in entries:
        for target in entry.related:
            if target not in names:
                raise ModConfigurationError(f"Missing related mod: {entry.name} -> {target}", entry.name)
    return ModCatalog(entries=tuple(entries))


def resolve_related_names(catalog: ModCatalog, names: Sequence[str]) -> tuple[str, ...]:
    if not names:
        raise ModRequestError("At least one mod name is required")
    index = {entry.name: entry for entry in catalog.entries}
    for name in names:
        if not isinstance(name, str) or re.fullmatch(MOD_NAME_PATTERN, name) is None:
            raise ModRequestError(f"Invalid mod name: {name!r}")
        if name not in index:
            raise ModRequestError(f"Unknown mod: {name}")
    visited: set[str] = set()
    order: list[str] = []
    stack = list(reversed(names))
    while stack:
        name = stack.pop()
        if name in visited:
            continue
        visited.add(name)
        order.append(name)
        stack.extend(reversed(index[name].related))
    return tuple(order)


def match_mod_keywords(catalog: ModCatalog, texts: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        entry.name for entry in catalog.entries
        if any(keyword in text for keyword in entry.keywords for text in texts)
    )


def read_mod_documents(
    root: Path,
    catalog: ModCatalog,
    names: Sequence[str],
) -> tuple[ModDocument, ...]:
    _require_kind(root, directory=True)
    index = {entry.name: entry for entry in catalog.entries}
    documents: list[ModDocument] = []
    total_bytes = 0
    for name in dict.fromkeys(names):
        if name not in index:
            raise ModRequestError(f"Unknown mod: {name}")
        directory = root / name
        _require_kind(directory, directory=True)
        body, size = _read_bounded(directory / MOD_DOCUMENT_FILENAME, MOD_MAX_DOCUMENT_BYTES)
        total_bytes += size
        if total_bytes > MOD_MAX_BATCH_SOURCE_BYTES:
            raise ModBudgetExceededError("Mod documents exceed the batch source byte budget")
        if not body.strip():
            raise ModConfigurationError(f"Empty mod document: {name}", name)
        documents.append(ModDocument(metadata=index[name], body=body))
    return tuple(documents)
