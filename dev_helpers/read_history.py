"""Read a project History using easysave and print a media-free diagnostic view."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterator
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
# 开发辅助脚本的受限例外：仅导入 origin仓库模型和 third库，不执行应用入口。
# 禁止生成依赖模块的 __pycache__，避免只读辅助操作写入源码目录。
sys.dont_write_bytecode = True
sys.path[:0] = [str(REPOSITORY_ROOT / "origin_agent"), str(REPOSITORY_ROOT / "third")]

from easysave import EasySaveConfig, raw_load
from easysave.private.util import type_format
from pydantic import BaseModel

from entity.constant import History_Version
from entity.messages import AudioBlock, History, ImageBlock, MediaBlock, VideoBlock
from entity.typeref import make_config


DATA_URL_PATTERN = re.compile(r"data:([^\s;,\"<>]+)(?:;[^\s,\"<>]*)?,[^\s\"<>]+")


def media_placeholder(value: str, kind: str) -> dict[str, Any]:
    """Describe a payload without exposing its URL or encoded contents."""
    if not isinstance(value, str):
        raise TypeError(f"Expected a string payload for {kind}")
    mime_type = None
    encoding = "base64" if kind == "audio" else "url"
    payload_chars = len(value)
    if value.startswith("data:"):
        header, separator, payload = value.partition(",")
        if not separator:
            raise ValueError("Malformed media data URL")
        mime_type = header[5:].split(";", 1)[0]
        encoding = "base64" if ";base64" in header else "data-url"
        payload_chars = len(payload)
    return {
        "placeholder": f"[{kind} omitted]",
        "encoding": encoding,
        "mime_type": mime_type,
        "original_chars": len(value),
        "payload_chars": payload_chars,
    }


def redact_data_urls(text: str) -> str:
    """Also hide inline data URLs in text and JSON-encoded tool results."""
    return DATA_URL_PATTERN.sub(
        lambda match: f"[data URL omitted: mime={match.group(1)}, chars={len(match.group(0))}]",
        text,
    )


def media_payload(block: MediaBlock) -> tuple[str, str, str]:
    """Read known media fields through the actual project model interfaces."""
    if isinstance(block, ImageBlock):
        return "image", "image_url", block.image_url
    if isinstance(block, AudioBlock):
        return "audio", "data", block.data
    if isinstance(block, VideoBlock):
        return "video", "video_url", block.video_url
    raise TypeError(f"Unsupported media model: {type(block).__name__}")


def project_value(value: Any, config: EasySaveConfig,
                  ancestors: frozenset[int] = frozenset()) -> Any:
    """Create display data without changing models or dumping media payloads."""
    if isinstance(value, Enum):
        return {"__type": type_format(type(value), config),
                "__value": project_value(value.value, config, ancestors)}
    if isinstance(value, str):
        return redact_data_urls(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if id(value) in ancestors:
        raise ValueError("Cyclic object in History display data")
    ancestors = ancestors | {id(value)}
    if isinstance(value, BaseModel):
        result: dict[str, Any] = {"__type": type_format(type(value), config)}
        media = media_payload(value) if isinstance(value, MediaBlock) else None
        # 使用 BaseModel 的公开迭代接口保留未来字段与嵌套模型，不复制字段表或反射。
        for field, item in value:
            result[field] = (
                media_placeholder(media[2], media[0])
                if media is not None and field == media[1]
                else project_value(item, config, ancestors)
            )
        return result
    if isinstance(value, (list, tuple, set)):
        return [project_value(item, config, ancestors) for item in value]
    if isinstance(value, dict):
        return {field: project_value(item, config, ancestors) for field, item in value.items()}
    raise TypeError(f"Unsupported History display value: {type(value).__name__}")


def load_history(path: Path, key: str = History_Version) -> tuple[History, dict[str, Any]]:
    """Restore the real History using the project's type mapping and easysave."""
    path = path.resolve()
    if not (path.name.lower().endswith(".es") or path.name.lower().endswith(".es.bak")):
        raise ValueError("Only .es files or explicitly selected .es.bak files may be read")
    raw = path.read_bytes()
    document = json.loads(raw)
    graph = document[key]
    if not isinstance(graph, dict):
        raise TypeError("Expected an easysave object graph")
    # raw_load 与 load 共用官方反序列化实现；只读一次以使指纹对应同一份字节快照。
    # 保持缺失字段默认值，但不跳过未知字段，也不调用业务层的工具配对清理。
    history = raw_load(graph, config=make_config(path))
    if not isinstance(history, History):
        raise TypeError("The selected easysave root is not a History")
    if not isinstance(history.messages, list):
        raise TypeError("History.messages must be a list")
    return history, {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def iter_media(value: Any, location: str = "content",
               ancestors: frozenset[int] = frozenset()) -> Iterator[tuple[str, MediaBlock]]:
    """Yield media models using public model and container iteration."""
    if isinstance(value, MediaBlock):
        yield location, value
        return
    if not isinstance(value, (BaseModel, list, tuple, set, dict)):
        return
    if id(value) in ancestors:
        raise ValueError(f"Cyclic object at {location}")
    ancestors = ancestors | {id(value)}
    if isinstance(value, (list, tuple, set)):
        for index, item in enumerate(value):
            yield from iter_media(item, f"{location}[{index}]", ancestors)
    else:
        fields = value.items() if isinstance(value, dict) else iter(value)
        for field, item in fields:
            yield from iter_media(item, f"{location}.{field}", ancestors)


def shorten_text(value: Any, max_chars: int, location: str, truncated: list[str]) -> Any:
    """Limit text for display only; report every shortened field's location."""
    if isinstance(value, str) and len(value) > max_chars:
        truncated.append(location)
        return value[:max_chars] + f" ... [truncated: {len(value) - max_chars} chars omitted]"
    if isinstance(value, list):
        return [shorten_text(item, max_chars, f"{location}[{index}]", truncated)
                for index, item in enumerate(value)]
    if isinstance(value, dict):
        return {field: shorten_text(item, max_chars, f"{location}.{field}", truncated)
                for field, item in value.items()}
    return value


def build_view(history: History, start: int = 0, limit: int = 10,
               max_text_chars: int = 4000, summary_only: bool = False) -> dict[str, Any]:
    """Project a page and a compact whole-History media inventory."""
    messages = history.messages
    config = make_config("")
    if start < 0 or start > len(messages) or limit < 1 or max_text_chars < 1:
        raise ValueError("Invalid message range or text limit")
    roles: Counter[str] = Counter()
    media_counts: Counter[str] = Counter()
    inventory = []
    last_user_index = None
    for index, message in enumerate(messages):
        roles[message.role.value] += 1
        if message is history.last_user_message:
            last_user_index = index
        for location, block in iter_media(message, "message"):
            kind, _, payload = media_payload(block)
            media_counts[kind] += 1
            inventory.append({
                "message_index": index,
                "location": location,
                "kind": kind,
                "media_id": block.media_id,
                "source_path": block.source_path,
                "source_tool_call_id": block.source_tool_call_id,
                "send_multimodal": block.send_multimodal,
                "format": block.format if isinstance(block, AudioBlock) else None,
                "payload": media_placeholder(payload, kind),
            })
    stop = start if summary_only else min(start + limit, len(messages))
    truncated: list[str] = []
    page = [] if summary_only else [
        {"index": index, "message": shorten_text(
            project_value(messages[index], config), max_text_chars,
            f"messages[{index}]", truncated)}
        for index in range(start, stop)
    ]
    view = {
        "history_type": type_format(type(history), config),
        "message_count": len(messages),
        "role_counts": dict(roles),
        "last_user_message_index": last_user_index,
        "media_counts": dict(media_counts),
        "media_inventory": inventory,
        "range": {"start": start, "stop": stop, "remaining": len(messages) - stop},
        "truncated_fields": truncated,
        "messages": page,
    }
    # The inventory may contain long metadata; apply the same explicit display limit.
    view["media_inventory"] = shorten_text(inventory, max_text_chars, "media_inventory", truncated)
    return view


def positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("The value must be positive")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--session", help="Exact session directory name (no directory scan)")
    source.add_argument("--path", type=Path, help="Explicit history.es path")
    parser.add_argument("--sessions-root", type=Path,
                        default=REPOSITORY_ROOT / "workspace" / "sessions")
    parser.add_argument("--key", default=History_Version)
    parser.add_argument("--start", type=int, default=0, help="Zero-based message index")
    parser.add_argument("--limit", type=positive_int, default=10)
    parser.add_argument("--max-text-chars", type=positive_int, default=4000)
    parser.add_argument("--max-output-chars", type=positive_int, default=24000)
    parser.add_argument("--summary", action="store_true", help="Inventory only; omit message bodies")
    args = parser.parse_args()
    if args.session is not None:
        if not args.session or args.session in {".", ".."} or any(
            character in args.session for character in "/\\:"
        ):
            parser.error("--session must be a single exact directory name")
        path = args.sessions_root / args.session / "history.es"
    else:
        path = args.path
    history, fingerprint = load_history(path, args.key)
    view = build_view(history, args.start, args.limit, args.max_text_chars, args.summary)
    view["source"] = {"path": str(path.resolve()), "key": args.key, **fingerprint}
    output = json.dumps(view, ensure_ascii=False, indent=2)
    if len(output) > args.max_output_chars:
        parser.error(
            f"Output needs {len(output)} characters (budget {args.max_output_chars}). "
            "Use --summary, lower --limit/--max-text-chars, or raise --max-output-chars. "
            "No History content was printed."
        )
    sys.stdout.reconfigure(encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
