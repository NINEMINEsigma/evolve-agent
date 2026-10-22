'''
长期记忆扩展上下文 hook。

把当前会话（含父链继承）的长期记忆合并后附加到最新 UserMessage 末尾，
标记为 ``<|im_remember_memory_start|>...<|im_remember_memory_end|>``。

内部模块的运行时导入一律放在函数体内：hook 以 spec_from_file_location 动态加载，
模块级导入会在 sys.path 尚未注入 agent 根目录时导致整个文件加载失败；
仅用于类型标注的导入放在 TYPE_CHECKING 块中，运行时不执行。
'''

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # 仅在类型检查时导入：hook 以 spec_from_file_location 动态加载，
    # 模块级导入内部模块会在 sys.path 尚未注入 agent 根目录时让整个文件加载失败。
    from system.context import RuntimeContext

logger = logging.getLogger(__name__)


def hook_tag_name(**kwargs) -> str:
    return "remember_memory"


def hook_message(
    session_id: str = "",
    workspace: str = "",
    runtime_ctx: "RuntimeContext | None" = None,
    **kwargs,
) -> str:
    if runtime_ctx is None:
        return ""
    try:
        from custom_tools.memory_tools._store import (
            FALLBACK_SESSION,
            load_all_memory,
            ensure_session_memory,
            collect_merged_memory,
            format_memory_text,
        )

        # 记忆文件路径
        memory_data_path: Path = runtime_ctx.agentspace / "memory_data.json"
        if not memory_data_path.exists():
            return ""
        # 加载整个 data 字典（文件不存在时返回空 dict）
        data = load_all_memory(memory_data_path)
        if not data:
            return ""
        # 获取当前会话 ID，优先使用 hook 调用时传入的 session_id
        sid = session_id or FALLBACK_SESSION
        # 在内存中建立 __parents__ 引用（不保存到磁盘，hook 是只读操作）
        ensure_session_memory(data, sid)
        # BFS 合并父链记忆（子覆盖父，多父按列表顺序后到优先）
        merged = collect_merged_memory(data, sid)
        return format_memory_text(merged)
    except Exception:
        logger.debug("memory_hook failed", exc_info=True)
        return ""
