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
'''

import json
from datetime import datetime
import os
import sys
from pathlib import Path


def hook_tag_name(session_id: str = "", workspace: str = "") -> str:
    return "external_knowledge"


def hook_message(session_id: str = "", workspace: str = "") -> str:
    cache_path = Path(workspace) / "session_cache" / session_id / "session_cache.json"
    now = datetime.now()

    result: dict[str, str] = {
        "current_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "current_platform": sys.platform,
        "session_id": session_id,
        "workspace": str(workspace),
    }

    if not cache_path.exists():
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_data = {"last_hook_time": now.isoformat()}
        cache_path.write_text(json.dumps(cache_data), encoding="utf-8")
        return json.dumps(result)

    else:
        cache_data = json.loads(cache_path.read_text(encoding="utf-8"))
        last_time = datetime.fromisoformat(cache_data["last_hook_time"])
        interval_seconds = int((now - last_time).total_seconds())

        cache_data["last_hook_time"] = now.isoformat()
        cache_path.write_text(json.dumps(cache_data), encoding="utf-8")

        result["last_conversation_interval_seconds"] = str(interval_seconds)
        if interval_seconds > 3600:
            hours = interval_seconds // 3600
            minutes = (interval_seconds % 3600) // 60
            result["long_interval_reminder"] = f"This conversation is {hours}h {minutes}m after the last one. Reminder: review previous context for continuity."

        return json.dumps(result)
    