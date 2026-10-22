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

内部导入全部放在函数体内：hook 以 spec_from_file_location 动态加载，
模块级导入会在 sys.path 尚未注入 agent 根目录时导致整个文件加载失败。
"""

import logging

logger = logging.getLogger(__name__)


def hook_tag_name(**kwargs) -> str:
    return "agentspace_changes"


def hook_message(session_id: str = "", workspace: str = "", **kwargs) -> str:
    """取出并清空 agentspace 待提交的变更摘要。

    直接查询 IAgentspaceService 的唯一业务服务，不修改 sys.path，
    也不经 gateway 的兼容层。无变更时返回空字符串。
    """
    try:
        from system.application import Application
        from interface.agentspace_service import IAgentspaceService
        result = Application.current().get_system(IAgentspaceService).flush_pending_changes()
        return result or ""
    except Exception:
        logger.debug("agentspace_changes_hook failed", exc_info=True)
        return ""