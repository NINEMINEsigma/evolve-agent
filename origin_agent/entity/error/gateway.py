"""Gateway-layer business exceptions."""


class GatewayPortBusyError(RuntimeError):
    """启动前端口已被占用的明确业务拒绝；调用方按普通停止处理。"""


class AgentspaceSendTimeout(TimeoutError):
    """Per-event send timeout for a slow agentspace WebSocket consumer."""


class AgentspaceConnectionClosed(Exception):
    """聊天 WebSocket 对端已断开：连接级例常结束，不作为应用级失败上报。

    由传输层发送回调在发现连接已关闭（或发送时收到对端断开）时抛出，
    转发循环原样传播。与 `AgentspaceSendTimeout` 的区别是对端已不存在，
    无需也不能再发送 1011 关闭帧。
    """
