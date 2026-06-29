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

新签名支持 **kwargs, 其中 kwargs["runtime_ctx"] 为 RuntimeContext 单例,
可从中读取 agentspace、fork_path、mode、llm_model 等运行时信息。
'''

import json
from datetime import datetime
import os
import sys
from pathlib import Path


def hook_tag_name(**kwargs) -> str:
    return "turn_time"


def hook_fixator(**kwargs) -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hook_message(session_id: str = "", workspace: str = "", **kwargs) -> str:
    # 这个cache文件会始终持久化
    cache_path: Path = Path(workspace) / "session_cache" / session_id / "time_hook.json"
    now = datetime.now()
    result_message = ""

    # 这个flag文件会在每次重启程序后都被刷新
    runtime_flag_path: Path = Path(workspace) / "flag.json"
    is_update_flag_cache = False
    # 读出hook的启动缓存
    with open(runtime_flag_path, "r", encoding="utf-8") as f:
        runtime_flag = json.load(f)
        if __file__ not in runtime_flag:
            result_message += f"This is the first message in this conversation after the program started, need to check if there are any background services or sub-conversations that need restarting."
            is_update_flag_cache = True
    # 存入hook的启动缓存
    if is_update_flag_cache:
        with open(runtime_flag_path, "w", encoding="utf-8") as f:
            runtime_flag[__file__] = {}
            json.dump(runtime_flag, f, ensure_ascii=False)


    if not cache_path.exists():
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_data = {"last_turn_time": now.isoformat()}
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False)
        result_message += "this is the first message of the conversation, or session cache is been cleared"
    else:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
        last_time = datetime.fromisoformat(cache_data["last_turn_time"])
        interval_seconds = int((now - last_time).total_seconds())

        cache_data["last_turn_time"] = now.isoformat()
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False)

        if interval_seconds > 3600:
            hours = interval_seconds // 3600
            minutes = (interval_seconds % 3600) // 60
            result_message += f"This conversation is {hours}h {minutes}m after the last one. Reminder: review previous context for continuity."
        else:
            result_message += f"This message between the previous one is {interval_seconds} seconds."
    return result_message