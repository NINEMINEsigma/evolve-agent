"""MCP OAuth lifecycle constants."""

# OAuth 回调等待超时（秒）— 等待用户在浏览器中完成授权的时间
OAUTH_CALLBACK_TIMEOUT: float = 300.0

# OAuth 回调 HTTP 服务器线程 join 超时（秒）— 关闭监听套接字后等待线程退出的宽限
OAUTH_CALLBACK_THREAD_JOIN_TIMEOUT: float = 5.0
