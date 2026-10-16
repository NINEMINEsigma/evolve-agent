"""离线导出的协作式结构复制与纯投影计算，不读取 live Loop。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import time
from collections.abc import Callable, Generator, Iterator
from typing import Any

from entity.constant import (
    SESSION_EXPORT_COPY_BATCH_NODES, SESSION_EXPORT_COPY_SLICE_SECONDS,
    SESSION_EXPORT_HISTORY_MAX_BYTES, SESSION_EXPORT_MAX_MESSAGES,
    SESSION_EXPORT_MAX_NODES, SESSION_EXPORT_MAX_ROWS,
    SESSION_EXPORT_READ_CHUNK_BYTES, SESSION_EXPORT_STRUCTURE_MAX_DEPTH,
)
from entity.messages import (
    AudioBlock, BaseMessage, CharacterConversationMessage, CharacterMessage,
    CharacterSystemMessage, ImageBlock, SystemStatusMessage, TextBlock,
    ToolResultMessage, VideoBlock,
)
from entity.puretype import MessageMetrics, SessionExportHistorySnapshot
from entity.puretype_after import SessionExportHistorySource
from entry.history_projection import project_history_content_rows

logger = logging.getLogger(__name__)


class SessionExportError(ValueError):
    """导出边界的已识别业务拒绝；服务层复用而不建立循环依赖。"""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class SessionExportLimitError(SessionExportError):
    def __init__(self, message: str) -> None:
        super().__init__("export_limit", message, 413)


class SessionExportChangedError(SessionExportError):
    def __init__(self) -> None:
        super().__init__("export_changed", "Session content changed; retry when idle", 409)


class SessionExportTimeoutError(SessionExportError):
    def __init__(self) -> None:
        super().__init__("export_timeout", "Export operation timed out; retry when idle", 408)


class SessionExportBusyError(SessionExportError):
    def __init__(self) -> None:
        super().__init__("session_busy", "Session must be idle before exporting", 409)


class _CopyBudget:
    """有方法的单请求复制预算，不是纯数据模型。"""

    def __init__(self) -> None:
        self.nodes = 0
        self.text_lower_bound = 0

    def visit(self, value: Any, depth: int) -> None:
        self.nodes += 1
        if self.nodes > SESSION_EXPORT_MAX_NODES:
            raise SessionExportLimitError(
                f"Structure nodes {self.nodes} exceed {SESSION_EXPORT_MAX_NODES}"
            )
        if depth > SESSION_EXPORT_STRUCTURE_MAX_DEPTH:
            raise SessionExportLimitError("History structure nesting limit exceeded")
        if isinstance(value, str):
            self.text_lower_bound += len(value)
            if self.text_lower_bound > SESSION_EXPORT_HISTORY_MAX_BYTES:
                raise SessionExportLimitError("History text exceeds byte budget lower bound")


def _copy_value(value: Any, budget: _CopyBudget) -> Generator[None, None, Any]:
    """显式迭代栈；容器逐项复制，不展开整个大数组或 dict。"""
    holder: list[Any] = []
    # 每个 frame 持有迭代器、目标容器、深度和源容器身份。
    stack: list[tuple[Iterator[tuple[Any, Any]], list | dict, int, int | None]] = [
        (iter(((None, value),)), holder, 0, None)
    ]
    active: set[int] = set()
    while stack:
        iterator, target, depth, identity = stack[-1]
        try:
            key, current = next(iterator)
        except StopIteration:
            stack.pop()
            if identity is not None:
                active.remove(identity)
            continue
        budget.visit(current, depth)
        if isinstance(target, dict):
            if not isinstance(key, str):
                raise SessionExportError("unsupported_history", "History object keys must be strings")
            budget.visit(key, depth)
        copied: Any
        if type(current) is dict or type(current) is list:
            if id(current) in active:
                raise SessionExportError("unsupported_history", "Cyclic History content is not supported")
            copied = {} if type(current) is dict else []
            children = iter(current.items()) if type(current) is dict else enumerate(current)
            active.add(id(current))
            stack.append((children, copied, depth + 1, id(current)))
        elif type(current) in (TextBlock, ImageBlock, AudioBlock, VideoBlock):
            # 当前四个正式块仅含不可变标量字段；浅复制保留全部声明字段。
            copied = current.model_copy()
            if isinstance(current, TextBlock):
                budget.visit(current.text, depth)
            elif isinstance(current, ImageBlock):
                budget.visit(current.image_url, depth)
            elif isinstance(current, AudioBlock):
                budget.visit(current.data, depth)
            else:
                budget.visit(current.video_url, depth)
            if current.forward_result_content:
                budget.visit(current.forward_result_content, depth)
        elif current is None or type(current) in (str, int, float, bool):
            if isinstance(current, float) and not math.isfinite(current):
                raise SessionExportError("unsupported_history", "Non-finite History number")
            copied = current
        else:
            raise SessionExportError("unsupported_history", "Unsupported History content type")
        if isinstance(target, list):
            target.append(copied)
        else:
            target[key] = copied
        yield None
    return holder[0]


def _copy_messages(messages: tuple[BaseMessage, ...]) -> Generator[None, None, tuple[BaseMessage, ...]]:
    budget = _CopyBudget()
    result: list[BaseMessage] = []
    known = (
        BaseMessage, SystemStatusMessage, CharacterMessage, CharacterSystemMessage,
        CharacterConversationMessage, ToolResultMessage,
    )
    for message in messages:
        if type(message) not in known:
            raise SessionExportError("unsupported_history", "Unsupported History message type")
        budget.visit(message, 0)
        content = yield from _copy_value(message.content, budget)
        copied = message.model_copy(update={"content": content})
        if isinstance(message, CharacterConversationMessage):
            visible = yield from _copy_value(message.visible_characters, budget)
            response = yield from _copy_value(message.response_characters, budget)
            calls = None
            if message.tool_calls is not None:
                calls = []
                for call in message.tool_calls:
                    budget.visit(call, 0)
                    budget.visit(call.function.arguments, 0)
                    calls.append(call.model_copy(update={"function": call.function.model_copy()}))
                    yield None
            copied = copied.model_copy(update={
                "visible_characters": visible, "response_characters": response,
                "tool_calls": calls,
            })
            for text in (message.reasoning, message.message_suffix, message.dynamic_message_suffix):
                if text:
                    budget.visit(text, 0)
        result.append(copied)
        yield None
    return tuple(result)


async def capture_export_messages(
    messages: tuple[BaseMessage, ...], assert_unchanged: Callable[[], None],
) -> tuple[BaseMessage, ...]:
    if len(messages) > SESSION_EXPORT_MAX_MESSAGES:
        raise SessionExportLimitError("History message limit exceeded")
    generator = _copy_messages(messages)
    started = time.monotonic()
    count = 0
    assert_unchanged()
    while True:
        try:
            next(generator)
        except StopIteration as complete:
            assert_unchanged()
            return complete.value
        count += 1
        if count >= SESSION_EXPORT_COPY_BATCH_NODES or (
            time.monotonic() - started >= SESSION_EXPORT_COPY_SLICE_SECONDS
        ):
            assert_unchanged()
            await asyncio.sleep(0)
            assert_unchanged()
            count = 0
            started = time.monotonic()


def export_history_digest(
    source: SessionExportHistorySource, metrics: dict[int, MessageMetrics],
    check: Callable[[], None] = lambda: None,
) -> str:
    """只在线程池处理已隔离模型，按 UTF-8 字节增量核算。"""
    digest = hashlib.sha256()
    digest.update(source.fallback_character.encode("utf-8"))
    digest.update(b"\n")
    size = 0
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))
    payloads = (
        message.model_dump(mode="json", serialize_as_any=True)
        for message in source.messages
    )
    for payload in payloads:
        check()
        for part in encoder.iterencode(payload):
            # iterencode 对大字符串可能产生单个大块，编码时继续分块。
            for offset in range(0, len(part), SESSION_EXPORT_READ_CHUNK_BYTES):
                check()
                chunk = part[offset:offset + SESSION_EXPORT_READ_CHUNK_BYTES].encode("utf-8")
                size += len(chunk)
                if size > SESSION_EXPORT_HISTORY_MAX_BYTES:
                    raise SessionExportLimitError("History JSON byte limit exceeded")
                digest.update(chunk)
        digest.update(b"\n")
    for index, value in sorted(metrics.items()):
        check()
        part = f"{index}:".encode() + value.model_dump_json().encode("utf-8")
        size += len(part)
        if size > SESSION_EXPORT_HISTORY_MAX_BYTES:
            raise SessionExportLimitError("History metrics byte limit exceeded")
        digest.update(part)
        digest.update(b"\n")
    return digest.hexdigest()


def project_export_history(
    source: SessionExportHistorySource, metrics: dict[int, MessageMetrics],
    check: Callable[[], None] = lambda: None,
) -> SessionExportHistorySnapshot:
    digest = export_history_digest(source, metrics, check)
    rows = project_history_content_rows(
        list(source.messages), 0, source.history_count, source.fallback_character, metrics,
    )
    check()
    if len(rows) > SESSION_EXPORT_MAX_ROWS:
        raise SessionExportLimitError("History projection row limit exceeded")
    return SessionExportHistorySnapshot(
        loop_instance_id=source.loop_instance_id, export_epoch=source.export_epoch,
        history_digest=digest, history_count=source.history_count, rows=rows,
    )
