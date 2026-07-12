import json
from datetime import datetime
import os
import sys
from pathlib import Path
from easysave import load, save
from system.context import RuntimeContext


__VERSION__ = "v0"

def hook_tag_name(**kwargs) -> str:
    return "remember_memory"


def hook_message(runtime_ctx: RuntimeContext, **kwargs) -> str:
    # 这个cache文件会始终持久化
    memory_data_path: Path = runtime_ctx.agentspace / "memory_data.json"
    if not memory_data_path.exists():
        return ""
    memory_data: dict[str, str] = load(__VERSION__, str(memory_data_path), dict[str, str])
    return "\n".join([f"{id}: {content}" for id, content in memory_data.items()])