"""
agentspace changes hook - 非持久化扩展上下文。

当用户通过网页编辑器编辑 agentspace 文件后，此 hook 将变更摘要注入到
下一条用户消息的末尾（仅影响当前最后一条用户消息，不会持久化到历史记录）。

格式：
<|im_agentspace_changes_start|>
User changes in agentspace:
- modified: path/to/file
- created: path/to/new
<|im_agentspace_changes_end|>
"""


def hook_tag_name(**kwargs) -> str:
    return "agentspace_changes"


def hook_message(session_id: str = "", workspace: str = "", **kwargs) -> str:
    """读取并清空 agentspace 操作日志，返回变更摘要。

    调用 gateway.server._flush_pending_changes() 将内存中的操作日志
    写入文件并清空，同时返回格式化的变更摘要。

    无变更时返回空字符串。
    """
    try:
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
        from gateway.server import _flush_pending_changes
        result = _flush_pending_changes()
        if result is None:
            return ""
        return result
    except Exception:
        return ""