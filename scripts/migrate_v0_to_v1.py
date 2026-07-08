"""迁移旧版 messages.jsonl 到新的 History / history.es (v1) 格式。

扫描 workspace/sessions/ 下的 messages.jsonl，将 OpenAI 格式消息
转换为 BaseMessage 子类，保存为 history.es。不删除原 messages.jsonl。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# 将仓库根目录加入导入路径，用于加载 config.py 与 origin_agent 模块
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 将 origin_agent 与 third 加入导入路径
ORIGIN_AGENT = REPO_ROOT / "origin_agent"
THIRD = REPO_ROOT / "third"
for p in (ORIGIN_AGENT, THIRD):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _load_config(load_key: str) -> Any:
    """非交互式加载 config.py 中的配置。

    config.py 在模块导入时会解析 sys.argv，因此需要先临时注入 --load。
    """
    original_argv = sys.argv
    sys.argv = [original_argv[0], "--load", load_key]
    try:
        import config
    finally:
        sys.argv = original_argv
    return config


from entity.constant import MAIN_AGENT_CHARACTER_NAME, USER_CHARACTER_NAME, History_Version as __History_Version__
from entity.messages import (
    CharacterConversationMessage,
    FunctionCall,
    History,
    ImageBlock,
    MessageBlock,
    TextBlock,
    ToolCall as HistoryToolCall,
    ToolResultMessage,
)
from entity.puretype import Role
from easysave import save

logger = logging.getLogger(__name__)


def _convert_content(content: str | list[dict[str, Any]] | None) -> str | list[MessageBlock]:
    """将 OpenAI 格式 content 转换为 History 可用的文本或 MessageBlock 列表。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        blocks: list[MessageBlock] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                blocks.append(TextBlock(text=str(block.get("text", ""))))
            elif block_type == "image_url":
                image_url_block = block.get("image_url")
                if isinstance(image_url_block, dict):
                    url = image_url_block.get("url", "")
                else:
                    url = str(image_url_block or "")
                blocks.append(ImageBlock(image_url=url))
        return blocks
    return str(content)


def _convert_tool_calls(tool_calls: list[dict[str, Any]] | None) -> list[HistoryToolCall] | None:
    """将 OpenAI 格式 tool_calls 转换为 HistoryToolCall 列表。"""
    if not tool_calls:
        return None
    result: list[HistoryToolCall] = []
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") or {}
        result.append(
            HistoryToolCall(
                id=str(tc.get("id", "")),
                type=str(tc.get("type", "function")),
                function=FunctionCall(
                    name=str(fn.get("name", "")),
                    arguments=str(fn.get("arguments", "{}")),
                ),
            )
        )
    return result or None


def _make_conversation_message(
    role: Role,
    character_name: str,
    content: str | list[MessageBlock],
    *,
    reasoning: str | None = None,
    tool_calls: list[HistoryToolCall] | None = None,
    visible_characters: list[str] | None = None,
) -> CharacterConversationMessage:
    """根据 content 类型构造 CharacterConversationMessage。"""
    if tool_calls:
        return CharacterConversationMessage.from_tool_calls(
            role=role,
            character_name=character_name,
            content=content if isinstance(content, str) else "",
            tool_calls=tool_calls,
            reasoning=reasoning,
            visible_characters=visible_characters,
        )
    return CharacterConversationMessage.from_text(
        role=role,
        character_name=character_name,
        text=content if isinstance(content, str) else json.dumps([b.as_object() for b in content], ensure_ascii=False),
        reasoning=reasoning,
        visible_characters=visible_characters,
    )


def migrate_session(session_dir: Path) -> dict[str, Any]:
    """迁移单个 session 目录，返回报告条目。"""
    report: dict[str, Any] = {
        "session_id": session_dir.name,
        "jsonl_path": str(session_dir / "messages.jsonl"),
        "es_path": str(session_dir / "history.es"),
        "entries_read": 0,
        "entries_migrated": 0,
        "skipped": 0,
        "errors": [],
    }

    jsonl_path = session_dir / "messages.jsonl"
    es_path = session_dir / "history.es"

    if not jsonl_path.exists():
        report["errors"].append("messages.jsonl not found")
        return report

    # NOTE: 需要强制覆盖时, 不要执行该if
    if True and es_path.exists():
    # if False and es_path.exists():
        report["errors"].append("history.es already exists; skipped")
        return report

    messages: list[Any] = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            report["entries_read"] += 1
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                report["errors"].append(f"JSON parse error: {exc}")
                report["skipped"] += 1
                continue

            if not isinstance(entry, dict):
                report["errors"].append(f"non-dict entry: {type(entry)}")
                report["skipped"] += 1
                continue

            role = entry.get("role")
            content = _convert_content(entry.get("content"))
            try:
                if role == "system":
                    # 丢弃已保存的 system prompt，运行时重新注入最新版本
                    report["skipped"] += 1
                    continue
                elif role == "user":
                    msg = _make_conversation_message(
                        Role.USER,
                        USER_CHARACTER_NAME,
                        content,
                        visible_characters=[MAIN_AGENT_CHARACTER_NAME],
                    )
                elif role == "assistant":
                    tool_calls = _convert_tool_calls(entry.get("tool_calls"))
                    msg = _make_conversation_message(
                        Role.ASSISTANT,
                        MAIN_AGENT_CHARACTER_NAME,
                        content,
                        reasoning=entry.get("reasoning_content"),
                        tool_calls=tool_calls,
                    )
                elif role == "tool":
                    msg = ToolResultMessage(
                        role=Role.TOOL,
                        character_name=MAIN_AGENT_CHARACTER_NAME,
                        tool_call_id=str(entry.get("tool_call_id", "")),
                        content=content if isinstance(content, str) else json.dumps([b.as_object() for b in content], ensure_ascii=False),
                    )
                else:
                    report["errors"].append(f"unknown role: {role}")
                    report["skipped"] += 1
                    continue
            except Exception as exc:
                report["errors"].append(f"entry conversion error: {exc}")
                report["skipped"] += 1
                continue

            messages.append(msg)
            report["entries_migrated"] += 1

    history = History(messages=messages)
    history.remove_unpaired_tool_calls()

    try:
        save(__History_Version__, str(es_path), history)
    except Exception as exc:
        report["errors"].append(f"failed to save history.es: {exc}")
        return report

    return report


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="迁移旧版 messages.jsonl 到 History / history.es")
    parser.add_argument("--load", type=str, default="default", help="config.json 中的配置键（默认 default）")
    parser.add_argument("--sessions-dir", type=str, default=None, help="sessions 目录路径（默认从 config.py 推导）")
    args = parser.parse_args()

    cfg = _load_config(args.load)
    sessions_dir: Path
    if args.sessions_dir:
        sessions_dir = Path(args.sessions_dir)
    else:
        sessions_dir = cfg.workspace_path / "sessions"

    if not sessions_dir.exists():
        logger.error("Session directory not found: %s", sessions_dir)
        sys.exit(1)

    reports: list[dict[str, Any]] = []
    for session_dir in sorted(sessions_dir.iterdir()):
        if not session_dir.is_dir():
            continue
        report = migrate_session(session_dir)
        reports.append(report)
        status = "OK" if not report["errors"] else "WARN"
        logger.info(
            "%s | session=%s read=%d migrated=%d skipped=%d errors=%d",
            status,
            report["session_id"],
            report["entries_read"],
            report["entries_migrated"],
            report["skipped"],
            len(report["errors"]),
        )
        for err in report["errors"]:
            logger.warning("  %s: %s", report["session_id"], err)

    total = len(reports)
    ok = sum(1 for r in reports if not r["errors"])
    logger.info("Migration complete | total=%d ok=%d warn=%d", total, ok, total - ok)


if __name__ == "__main__":
    main()