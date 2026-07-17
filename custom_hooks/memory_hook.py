from pathlib import Path
from system.context import RuntimeContext

from custom_tools.memory_tools._store import (
    FALLBACK_SESSION,
    load_all_memory,
    ensure_session_memory,
    collect_merged_memory,
    format_memory_text,
)


def hook_tag_name(**kwargs) -> str:
    return "remember_memory"


def hook_message(runtime_ctx: RuntimeContext, **kwargs) -> str:
    # 记忆文件路径
    memory_data_path: Path = runtime_ctx.agentspace / "memory_data.json"
    # 加载整个 data 字典（文件不存在时返回空 dict）
    data = load_all_memory(memory_data_path)
    if not data:
        return ""
    # 获取当前会话 ID，从 hook 调用时传入的 kwargs 中读取
    session_id = kwargs.get("session_id", "") or FALLBACK_SESSION
    # 在内存中建立 __parents__ 引用（不保存到磁盘，hook 是只读操作）
    ensure_session_memory(data, session_id)
    # BFS 合并父链记忆（子覆盖父，多父按列表顺序后到优先）
    merged = collect_merged_memory(data, session_id)
    return format_memory_text(merged)