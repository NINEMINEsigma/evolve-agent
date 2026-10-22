'''
默认的一个扩展上下文脚本, 在custom_hooks目录下添加脚本并编写函数:
- hook_tag_name
- hook_message
每个最新的UserMessage都会附加hook消息, 如最新消息为"现在几点了",
那么在仅有本脚本的情况下上下文会呈现:
f"现在几点了<|im_{hook_tag_name()}_start|>{hook_message()}<|im_{hook_tag_name()}_end|>"

被附加的块称为扩展上下文, 这些块仅会在发送会话时附加在最后一条UserMessage的末尾,
这些块既不会出现在持久化的会话的历史记录文件中,
也不会在下一轮对话中被保留在那个成为倒数第二个UserMessage的末尾,
而只会出现在最后一轮对话的UserMessage的末尾.

`hook_message` 按会话追踪轮次间隔, 并在进程重启后的首轮附加一次重启提醒:
- 轮次缓存写在 `workspace/session_cache/<session_id>/time_hook.json`
- 启动标记读取 `workspace/flag.json`（由 `__main__.py` 每次启动时刷新）

`workspace` 形参就是 `RuntimeContext.workspace`（即 `workspace/` 根目录），
`flag.json` 与其同级；`session_cache` 也在该根目录下。两处读取都必须容忍文件缺失，
否则一次 `FileNotFoundError` 就会让整块上下文被调用方丢弃。

新签名支持 **kwargs, 其中 kwargs["runtime_ctx"] 为 RuntimeContext 单例,
可从中读取 agentspace、fork_path、mode、llm_model 等运行时信息。
'''

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# 进程启动标记文件名（由 __main__.py 写入 workspace 根目录）
_RUNTIME_FLAG_NAME = "flag.json"
# 轮次缓存目录名（位于 workspace 根目录）
_SESSION_CACHE_DIR_NAME = "session_cache"
# 超过该秒数视为跨会话中断，附加连续性提醒
_LONG_GAP_SECONDS = 3600


def hook_tag_name(**kwargs) -> str:
    return "turn_time"


def hook_fixator(**kwargs) -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _read_runtime_flag(runtime_flag_path: Path) -> dict | None:
    """读取进程启动标记；文件缺失或损坏时返回 None。"""
    try:
        with open(runtime_flag_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.debug("Runtime flag file not found: %s", runtime_flag_path)
        return None
    except (OSError, ValueError):
        logger.warning("Failed to read runtime flag file: %s", runtime_flag_path, exc_info=True)
        return None
    return data if isinstance(data, dict) else None


def _mark_hook_started(runtime_flag_path: Path, runtime_flag: dict) -> None:
    """把本 hook 登记进启动标记；父目录缺失或写入失败只记日志，不影响上下文。"""
    runtime_flag[__file__] = {}
    try:
        runtime_flag_path.parent.mkdir(parents=True, exist_ok=True)
        with open(runtime_flag_path, "w", encoding="utf-8") as f:
            json.dump(runtime_flag, f, ensure_ascii=False)
    except OSError:
        logger.warning("Failed to write runtime flag file: %s", runtime_flag_path, exc_info=True)


def hook_message(session_id: str = "", workspace: str = "", **kwargs) -> str:
    # 这个cache文件会始终持久化
    cache_path: Path = Path(workspace) / _SESSION_CACHE_DIR_NAME / session_id / "time_hook.json"
    now = datetime.now()
    parts: list[str] = []

    # 这个flag文件会在每次重启程序后都被刷新
    runtime_flag_path: Path = Path(workspace) / _RUNTIME_FLAG_NAME
    runtime_flag = _read_runtime_flag(runtime_flag_path)
    if runtime_flag is not None and __file__ not in runtime_flag:
        parts.append(
            "This is the first message in this conversation after the program started, "
            "need to check if there are any background services or sub-conversations that need restarting."
        )
        _mark_hook_started(runtime_flag_path, runtime_flag)

    # 读出/写入轮次缓存
    last_time: datetime | None = None
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
        last_time = datetime.fromisoformat(cache_data["last_turn_time"])
    except FileNotFoundError:
        parts.append("this is the first message of the conversation, or session cache is been cleared")
    except (OSError, ValueError, KeyError, TypeError):
        logger.warning("Failed to read turn cache, treated as first turn: %s", cache_path, exc_info=True)
        parts.append("this is the first message of the conversation, or session cache is been cleared")

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"last_turn_time": now.isoformat()}, f, ensure_ascii=False)
    except OSError:
        logger.warning("Failed to write turn cache: %s", cache_path, exc_info=True)

    if last_time is not None:
        interval_seconds = int((now - last_time).total_seconds())
        if interval_seconds > _LONG_GAP_SECONDS:
            hours = interval_seconds // _LONG_GAP_SECONDS
            minutes = (interval_seconds % _LONG_GAP_SECONDS) // 60
            parts.append(
                f"This conversation is {hours}h {minutes}m after the last one. "
                "Reminder: review previous context for continuity."
            )
        else:
            parts.append(f"This message between the previous one is {interval_seconds} seconds.")

    return " ".join(parts)