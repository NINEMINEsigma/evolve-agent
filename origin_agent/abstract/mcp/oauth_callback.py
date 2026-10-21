"""One OAuth HTTP callback and its native listener lifetime."""

from __future__ import annotations

import asyncio
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from entity.constant import OAUTH_CALLBACK_THREAD_JOIN_TIMEOUT
from system.lifecycle import LifecycleFailure


class CallbackHTTPServer(HTTPServer):
    def get_request(self) -> tuple[socket.socket, Any]:
        connection, address = super().get_request()
        # 浏览器只发送短HTTP回调；限制半开客户端读取，避免join被无限阻塞。
        connection.settimeout(1.0)
        return connection, address

    def handle_error(
        self,
        request: Any,
        client_address: Any
        ) -> None:
        error = sys.exception()
        if error is None:
            raise LifecycleFailure("OAuth callback request failed without an exception")
        raise error


class OAuthCallbackServer:
    def __init__(
        self,
        port: int,
        handler: type[BaseHTTPRequestHandler],
        result: dict[str, str | None]
        ) -> None:
        self.result = result
        self._loop = asyncio.get_running_loop()
        self._server = CallbackHTTPServer(("127.0.0.1", port), handler)
        self._server.timeout = 0.2
        self._stop = threading.Event()
        self._finished: asyncio.Future[None] = self._loop.create_future()
        self._thread = threading.Thread(target=self._serve, name=f"mcp-oauth-{port}", daemon=True)
        self._started = False
        self._closed = False
        self._error: BaseException | None = None
        self._close_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._started or self._closed:
            raise LifecycleFailure("OAuth callback listener cannot be restarted")
        self._thread.start()
        self._started = True

    def _serve(self) -> None:
        try:
            while not self._stop.is_set():
                self._server.handle_request()
                if self.result["auth_code"] is not None or self.result["error"] is not None:
                    return
        except BaseException as error:
            self._error = error
        finally:
            self._loop.call_soon_threadsafe(self._finish)

    def _finish(self) -> None:
        if not self._finished.done():
            self._finished.set_result(None)

    async def wait(self, timeout: float) -> None:
        async with asyncio.timeout(timeout):
            await asyncio.shield(self._finished)
        if self._error is not None:
            raise self._error

    def _join_and_close(self) -> None:
        if self._started:
            self._thread.join(OAUTH_CALLBACK_THREAD_JOIN_TIMEOUT)
            if self._thread.is_alive():
                raise LifecycleFailure("OAuth callback listener did not exit")
        self._server.server_close()
        self._closed = True

    def request_stop(self) -> None:
        self._stop.set()

    async def aclose(self) -> None:
        self.request_stop()
        if self._close_task is None:
            self._close_task = asyncio.create_task(
                asyncio.to_thread(self._join_and_close), name="mcp-oauth-callback-close",
            )
            self._close_task.add_done_callback(self._observe_close)
        done, _ = await asyncio.wait({self._close_task}, timeout=OAUTH_CALLBACK_THREAD_JOIN_TIMEOUT + 1)
        if not done:
            raise LifecycleFailure("OAuth callback cleanup remains active")
        self._close_task.result()

    @staticmethod
    def _observe_close(task: asyncio.Task[None]) -> None:
        # Manager保留失败清理记录；aclose和最终系统关闭仍会读取并传播该异常。
        if not task.cancelled():
            task.exception()

    @property
    def is_idle(self) -> bool:
        return (
            self._closed and not self._thread.is_alive()
            and (self._close_task is None or self._close_task.done())
        )
