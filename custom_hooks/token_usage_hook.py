'''
Token 使用量上下文扩展 hook。
在每条用户消息末尾注入当前会话的 token 总消耗量和已消耗上下文 token 数。
数据从内存中的 loop 实例读取，不访问磁盘。

内部导入全部放在函数体内：hook 以 spec_from_file_location 动态加载，
模块级导入会在 sys.path 尚未注入 agent 根目录时导致整个文件加载失败。
'''

import logging

logger = logging.getLogger(__name__)


def hook_tag_name(**kwargs) -> str:
    return "token_usage"


def hook_message(session_id: str = "", workspace: str = "", **kwargs) -> str:
    try:
        from system.application import Application
        from interface.session_manager import ISessionManager
        sm = Application.current().get_system(ISessionManager)
        if sm is None:
            return ""
        loop_wrap = sm.get_loop(session_id)
        if loop_wrap is None:
            return ""
        token_usage = loop_wrap.loop.get_token_usage()
        context_tokens = loop_wrap.loop.get_context_tokens()
        return f"Token usage: cumulative_session_total={token_usage} (cumulative tokens consumed across all turns, NOT current context occupancy), current_context_tokens={context_tokens} (tokens currently occupying the context window)."
    except Exception:
        logger.debug("token_usage_hook failed", exc_info=True)
        return ""
