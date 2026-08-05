'''
Token 使用量上下文扩展 hook。
在每条用户消息末尾注入当前会话的 token 总消耗量和已消耗上下文 token 数。
数据从内存中的 loop 实例读取，不访问磁盘。
'''


def hook_tag_name(**kwargs) -> str:
    return "token_usage"


def hook_message(session_id: str = "", workspace: str = "", **kwargs) -> str:
    try:
        from system.application import Application
        sm = Application.current().session_manager
        if sm is None:
            return ""
        loop_wrap = sm.get_loop(session_id)
        if loop_wrap is None:
            return ""
        token_usage = loop_wrap.loop.get_token_usage()
        context_tokens = loop_wrap.loop.get_context_tokens()
        return f"Token usage: total={token_usage}, context={context_tokens}."
    except Exception:
        return ""