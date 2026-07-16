"""LSP (Language Server Protocol) 客户端 — pyright 子进程管理 + JSON-RPC over stdio。

全局共享单例，懒启动。agent 通过 ``lsp_start`` 工具指定根目录并启动 pyright 后，
才能使用 ``lsp_references``、``lsp_definition``、``lsp_diagnostics``、
``lsp_symbols``、``lsp_refresh`` 等查询能力。

无 ``lsp_stop``；重复 ``lsp_start`` 直接替换根目录并重启 pyright 进程。
agent 进程退出时由 ``main.py`` 调用 ``cleanup_lsp()`` 强制清理。

通信模型：JSON-RPC 2.0 over stdio，帧格式 ``Content-Length: N\\r\\n\\r\\n{json}``。
独立的 daemon 线程持续读取 pyright stdout，按 ``id`` 分发响应，按 ``method`` 路由通知。
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import struct
import subprocess  # nosec
import sys
import threading
from pathlib import Path
from typing import Any

from entity.puretype import LSPDefinition, LSPDiagnostic, LSPReference, LSPState, LSPSymbol
from system.sandbox import Sandbox, SandboxError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_LSP_REQUEST_TIMEOUT: float = 10.0       # 单次 LSP 请求超时（秒）
_LSP_START_TIMEOUT: float = 30.0         # 启动 + 索引就绪超时（秒）
_LSP_DIAGNOSTICS_SETTLE_TIME: float = 0.8 # didChange 后等待 diagnostics 推送的短暂 sleep
_KILL_WAIT_TIMEOUT: int = 5              # 杀死旧进程后等待退出的秒数

# pyright 支持的代码文件扩展名
_LSP_CODE_EXTENSIONS: frozenset[str] = frozenset({".py"})

# LSP severity 数值 → 字符串映射
_SEVERITY_MAP: dict[int, str] = {
    1: "error",
    2: "warning",
    3: "information",
    4: "hint",
}

# LSP SymbolKind 数值 → 字符串映射（只覆盖常见类型）
_SYMBOL_KIND_MAP: dict[int, str] = {
    1: "File", 2: "Module", 3: "Namespace", 4: "Package",
    5: "Class", 6: "Method", 7: "Property", 8: "Field",
    9: "Constructor", 10: "Enum", 11: "Interface", 12: "Function",
    13: "Variable", 14: "Constant", 15: "String", 16: "Number",
    17: "Boolean", 18: "Array", 19: "Object", 20: "Key",
    21: "Null", 22: "EnumMember", 23: "Struct", 24: "Event",
    25: "Operator", 26: "TypeParameter",
}


# ---------------------------------------------------------------------------
# LSPManager
# ---------------------------------------------------------------------------

class LSPManager:
    """pyright LSP server 的全局单例管理器。

    生命周期: IDLE → STARTING → READY → (lsp_start 替换) → STARTING → READY → ...
    线程安全: 所有公开方法通过 ``_lock`` 序列化。
    """

    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._state: LSPState = LSPState.IDLE
        self._process: subprocess.Popen | None = None
        self._root_path: Path | None = None
        self._root_uri: str | None = None
        self._sandbox: Sandbox | None = None
        self._next_id: int = 1
        self._pending: dict[int, dict[str, Any]] = {}
        self._diagnostics_cache: dict[str, list[LSPDiagnostic]] = {}
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # -- 公开属性 --------------------------------------------------

    @property
    def state(self) -> LSPState:
        with self._lock:
            return self._state

    def is_ready(self) -> bool:
        with self._lock:
            return self._state == LSPState.READY

    def get_root_uri(self) -> str | None:
        with self._lock:
            return self._root_uri

    # -- start -----------------------------------------------------

    def start(self, root_logical: str, sandbox: Sandbox) -> dict:
        """启动或替换 pyright 实例。

        *root_logical* — 逻辑路径（如 ``"fork:"``），通过 sandbox 解析为真实路径。
        *sandbox* — 当前 Sandbox 实例，用于路径映射。

        返回 dict:
        - 成功: ``{"started": true, "root": "<逻辑路径>", "root_uri": "<file URI>"}`
        - 替换: 额外包含 ``"replaced": true, "previous_root": "<旧逻辑路径>"}``
        - 失败: ``{"error": "..."}``
        """
        with self._lock:
            # 解析根目录
            try:
                resolved = sandbox.resolve_read(root_logical)
            except SandboxError as exc:
                return {"error": f"Cannot resolve root path: {exc}"}

            root_path: Path = resolved.real
            if not root_path.is_dir():
                return {"error": f"Root path is not a directory: {root_logical}"}

            # 查找 pyright-langserver
            pyright_bin = self._find_pyright()
            if pyright_bin is None:
                return {"error": "pyright-langserver not found. Install with: pip install pyright"}

            # 如果已有运行实例，先清理
            previous_root: str | None = None
            if self._process is not None:
                previous_root = self._root_uri or ""
                self._kill_existing()

            # 更新状态
            self._state = LSPState.STARTING
            self._root_path = root_path
            self._root_uri = root_path.as_uri()
            self._sandbox = sandbox
            self._diagnostics_cache.clear()
            self._pending.clear()
            self._next_id = 1

            # 获取或创建事件循环
            try:
                self._loop = asyncio.get_event_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()

            # 启动子进程
            try:
                popen_kwargs: dict = {
                    "stdin": subprocess.PIPE,
                    "stdout": subprocess.PIPE,
                    "stderr": subprocess.PIPE,
                }
                if sys.platform == "win32":
                    from system.subprocess_utils import windows_process_group_flags
                    popen_kwargs["creationflags"] = windows_process_group_flags()

                self._process = subprocess.Popen(
                    [pyright_bin, "--stdio"],
                    **popen_kwargs,
                )
            except Exception as exc:
                self._state = LSPState.IDLE
                return {"error": f"Failed to start pyright: {exc}"}

            # 启动 stderr 读取线程（stderr 不与 stdout 竞争，可以立即启动）
            self._stderr_thread = threading.Thread(
                target=self._stderr_loop,
                name="lsp-stderr",
                daemon=True,
            )
            self._stderr_thread.start()

            # 初始化握手（同步读取 stdout，此时 reader 线程尚未启动）
            try:
                self._do_initialize()
            except Exception as exc:
                self._state = LSPState.IDLE
                self._kill_existing()
                return {"error": f"LSP initialization failed: {exc}"}

            # sanity check
            try:
                self._do_sanity_check()
            except Exception as exc:
                self._state = LSPState.IDLE
                self._kill_existing()
                return {"error": f"LSP sanity check failed: {exc}"}

            self._state = LSPState.READY

            # 初始化完成，现在启动 stdout reader 线程处理后续消息
            self._reader_thread = threading.Thread(
                target=self._read_loop,
                name="lsp-reader",
                daemon=True,
            )
            self._reader_thread.start()

            result: dict = {
                "started": True,
                "root": root_logical,
                "root_uri": self._root_uri,
            }
            if previous_root:
                result["replaced"] = True
                result["previous_root"] = previous_root
            return result

    # -- 查询方法 --------------------------------------------------

    async def references(
        self, logical_path: str, line: int, column: int, sandbox: Sandbox
    ) -> list[LSPReference]:
        if not self.is_ready():
            return []
        uri = self._resolve_to_uri(logical_path, sandbox)
        if uri is None:
            return []
        params = {
            "textDocument": {"uri": uri},
            "position": {"line": line - 1, "character": column - 1},
            "context": {"includeDeclaration": True},
        }
        result = await self._request("textDocument/references", params)
        if result is None:
            return []
        refs: list[LSPReference] = []
        for loc in result if isinstance(result, list) else []:
            ref = self._location_to_reference(loc, sandbox)
            if ref is not None:
                refs.append(ref)
        return refs

    async def definition(
        self, logical_path: str, line: int, column: int, sandbox: Sandbox
    ) -> LSPDefinition | None:
        if not self.is_ready():
            return None
        uri = self._resolve_to_uri(logical_path, sandbox)
        if uri is None:
            return None
        params = {
            "textDocument": {"uri": uri},
            "position": {"line": line - 1, "character": column - 1},
        }
        result = await self._request("textDocument/definition", params)
        if result is None:
            return None
        # definition 可能返回单个 Location 或 Location[] 或 LocationLink[]
        loc = result[0] if isinstance(result, list) and result else result
        if not isinstance(loc, dict):
            return None
        return self._location_to_definition(loc, sandbox)

    async def diagnostics(
        self, logical_path: str, sandbox: Sandbox
    ) -> list[LSPDiagnostic]:
        if not self.is_ready():
            return []
        uri = self._resolve_to_uri(logical_path, sandbox)
        if uri is None:
            return []
        with self._lock:
            return list(self._diagnostics_cache.get(uri, []))

    async def symbols(
        self, logical_path: str, sandbox: Sandbox
    ) -> list[LSPSymbol]:
        if not self.is_ready():
            return []
        uri = self._resolve_to_uri(logical_path, sandbox)
        if uri is None:
            return []
        params = {"textDocument": {"uri": uri}}
        result = await self._request("textDocument/documentSymbol", params)
        if result is None:
            return []
        return [self._to_symbol(s) for s in result if isinstance(s, dict)]

    async def refresh(
        self, logical_path: str | None, sandbox: Sandbox
    ) -> dict:
        if not self.is_ready():
            return {"error": "LSP not started. Call lsp_start first."}
        if logical_path is not None:
            uri = self._resolve_to_uri(logical_path, sandbox)
            if uri is None:
                return {"error": f"Cannot map path to LSP workspace: {logical_path}"}
            # 读取磁盘最新内容并发 didChange
            try:
                content = sandbox.read(logical_path, limit=0)
            except SandboxError as exc:
                return {"error": str(exc)}
            self._notify("textDocument/didChange", {
                "textDocument": {"uri": uri, "version": 1},
                "contentChanges": [{"text": content}],
            })
            # 清除该文件的缓存 diagnostics
            with self._lock:
                self._diagnostics_cache.pop(uri, None)
            return {"refreshed": True, "file": logical_path}
        else:
            # 全工作区刷新 — 通过 workspace/didChangeConfiguration 触发重分析
            self._notify("workspace/didChangeConfiguration", {"settings": {}})
            with self._lock:
                self._diagnostics_cache.clear()
            return {"refreshed": True, "scope": "workspace"}

    # -- didChange + diagnostics 附加 (供 filesystem.py 调用) -----------

    def notify_did_change(self, logical_path: str, content: str, sandbox: Sandbox) -> None:
        """通知 LSP 文件内容已变更。

        如果 LSP 未启动或文件不在 workspace 范围内，静默忽略。
        """
        if not self.is_ready():
            return
        uri = self._resolve_to_uri(logical_path, sandbox)
        if uri is None:
            return
        self._notify("textDocument/didChange", {
            "textDocument": {"uri": uri, "version": 1},
            "contentChanges": [{"text": content}],
        })
        # 清除该文件的缓存 diagnostics，等待 pyright 重新推送
        with self._lock:
            self._diagnostics_cache.pop(uri, None)

    def get_cached_diagnostics(self, uri: str) -> list[LSPDiagnostic]:
        with self._lock:
            return list(self._diagnostics_cache.get(uri, []))

    def is_in_workspace(self, real_path: Path) -> bool:
        """检查真实路径是否在当前 LSP 根目录范围内。"""
        with self._lock:
            if self._root_path is None:
                return False
            try:
                real_path.relative_to(self._root_path)
                return True
            except ValueError:
                return False

    # -- cleanup ---------------------------------------------------

    def cleanup(self) -> int:
        """强制终止 pyright 进程。返回 killed count。"""
        with self._lock:
            if self._process is None:
                self._state = LSPState.IDLE
                return 0
            killed = self._kill_existing()
            self._state = LSPState.IDLE
            return 1 if killed else 0

    # -- 内部方法 --------------------------------------------------

    def _find_pyright(self) -> str | None:
        return shutil.which("pyright-langserver")

    def _path_to_uri(self, path: Path) -> str:
        return path.as_uri()

    def _resolve_to_uri(self, logical_path: str, sandbox: Sandbox) -> str | None:
        try:
            resolved = sandbox.resolve_read(logical_path)
            if not self.is_in_workspace(resolved.real):
                return None
            return self._path_to_uri(resolved.real)
        except SandboxError:
            return None

    def _uri_to_logical(self, uri: str, sandbox: Sandbox) -> str | None:
        """将 file URI 反向映射为逻辑路径。"""
        if not uri.startswith("file://"):
            return None
        # 将 URI 转为 Path
        try:
            from urllib.parse import urlparse, unquote
            parsed = urlparse(uri)
            real_path = Path(unquote(parsed.path))
            if sys.platform == "win32" and len(parsed.path) > 2 and parsed.path[1] == ":":
                # Windows: file:///D:/path → /D:/path → D:/path
                real_path = Path(parsed.path.lstrip("/"))
        except Exception:
            return None

        # 与各命名空间 base 路径比较
        if self._sandbox is None:
            return None
        ns_map = {
            "fork": self._sandbox._ctx.fork_path,
            "ws": self._sandbox._ctx.agentspace,
            "fix": self._sandbox._ctx.fix_path,
            "skills": self._sandbox._ctx.skills_path,
        }
        for ns, base in ns_map.items():
            if base is None:
                continue
            try:
                rel = real_path.relative_to(base)
                return f"{ns}:{rel.as_posix()}"
            except ValueError:
                continue
        return None

    def _send_request(self, method: str, params: dict) -> int:
        """发送 JSON-RPC 请求，返回 msg_id。"""
        msg_id = self._next_id
        self._next_id += 1
        message = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params,
        }
        # 用 threading.Event 做同步等待，避免跨事件循环的 Future 问题
        event: threading.Event = threading.Event()
        self._pending[msg_id] = {
            "event": event,
            "result": None,
            "error": None,
        }
        self._write_message(message)
        return msg_id

    async def _request(self, method: str, params: dict) -> Any:
        """发送请求并在线程池中同步等待响应（带超时）。"""
        with self._lock:
            if self._state != LSPState.READY:
                return None
            if self._process is None or self._process.poll() is not None:
                self._state = LSPState.IDLE
                return None
            msg_id = self._send_request(method, params)

        # 在线程池中等待 Event 被设置，避免阻塞事件循环
        def _wait() -> Any:
            pending = self._pending.get(msg_id)
            if pending is None:
                return None
            event: threading.Event = pending["event"]
            if event.wait(timeout=_LSP_REQUEST_TIMEOUT):
                if pending["error"] is not None:
                    logger.warning("LSP request error: %s -> %s", method, pending["error"])
                    return None
                return pending["result"]
            else:
                logger.warning("LSP request timeout: %s", method)
                with self._lock:
                    self._pending.pop(msg_id, None)
                return None

        return await asyncio.to_thread(_wait)

    def _notify(self, method: str, params: dict) -> None:
        """发送 JSON-RPC 通知（无 id，无响应）。"""
        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        self._write_message(message)

    def _write_message(self, message: dict) -> None:
        """写入一条 JSON-RPC 消息到 pyright stdin。"""
        if self._process is None or self._process.stdin is None:
            return
        body = json.dumps(message).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        try:
            self._process.stdin.write(header + body)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            logger.warning("LSP write failed: %s", exc)

    def _read_loop(self) -> None:
        """daemon 线程：持续读取 pyright stdout 并分发消息。"""
        while True:
            try:
                if self._process is None or self._process.stdout is None:
                    logger.warning("LSP read loop: process or stdout is None")
                    break
                if self._process.poll() is not None:
                    logger.warning("LSP read loop: process exited (poll=%s)", self._process.poll())
                    break
                msg = self._read_message()
                if msg is None:
                    # readline 返回空 bytes = EOF，检查进程是否真的退出
                    if self._process.poll() is not None:
                        logger.warning("LSP read loop: EOF and process exited (poll=%s)", self._process.poll())
                        break
                    else:
                        # 进程仍存活但 readline 返回空，可能是暂时性 I/O 问题
                        logger.debug("LSP read loop: readline returned None but process alive, retrying")
                        import time as _time
                        _time.sleep(0.1)
                        continue
                self._dispatch_message(msg)
            except json.JSONDecodeError:
                # 跳过无法解析的消息，不终止 reader 线程
                logger.debug("LSP: skipped unparseable message", exc_info=True)
                continue
            except Exception:
                logger.warning("LSP read loop error", exc_info=True)
                break
        # 进程退出，标记所有 pending 请求为 error
        with self._lock:
            self._state = LSPState.IDLE
            for pending in self._pending.values():
                pending["error"] = "LSP process exited"
                pending["event"].set()
            self._pending.clear()

    def _read_message(self) -> dict | None:
        """读取一条 JSON-RPC 消息（Content-Length 帧格式）。"""
        if self._process is None or self._process.stdout is None:
            return None
        # 读取 header
        headers: dict[str, str] = {}
        while True:
            line = self._process.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                break
            if b":" in line:
                key, _, value = line.partition(b":")
                headers[key.decode("ascii").strip()] = value.decode("ascii").strip()
        content_length = int(headers.get("Content-Length", "0"))
        if content_length == 0:
            return None
        # 循环读取直到凑满 content_length 字节（Windows 管道可能分次返回）
        body = b""
        remaining = content_length
        while remaining > 0:
            chunk = self._process.stdout.read(remaining)
            if not chunk:
                return None
            body += chunk
            remaining = content_length - len(body)
        return json.loads(body.decode("utf-8"))

    def _dispatch_message(self, msg: dict) -> None:
        """分发收到的 JSON-RPC 消息。"""
        if "id" in msg and ("result" in msg or "error" in msg):
            # 响应
            msg_id = msg["id"]
            with self._lock:
                pending = self._pending.pop(msg_id, None)
            if pending is not None:
                if "error" in msg:
                    pending["error"] = msg["error"]
                else:
                    pending["result"] = msg.get("result")
                pending["event"].set()
        elif "method" in msg:
            # 通知
            method = msg["method"]
            params = msg.get("params", {})
            if method == "textDocument/publishDiagnostics":
                self._on_publish_diagnostics(params)
            elif method == "window/logMessage":
                self._on_log_message(params)
            # initialized 通知在 _do_initialize 中同步处理

    def _on_publish_diagnostics(self, params: dict) -> None:
        """处理 publishDiagnostics 通知。"""
        uri = params.get("uri", "")
        diagnostics_raw = params.get("diagnostics", [])
        diags: list[LSPDiagnostic] = []
        for d in diagnostics_raw:
            try:
                rng = d.get("range", {})
                start = rng.get("start", {})
                end = rng.get("end", {})
                diags.append(LSPDiagnostic(
                    severity=_SEVERITY_MAP.get(d.get("severity", 1), "error"),
                    line=start.get("line", 0) + 1,
                    column=start.get("character", 0) + 1,
                    end_line=end.get("line", 0) + 1,
                    end_column=end.get("character", 0) + 1,
                    message=d.get("message", ""),
                    source=d.get("source", "pyright"),
                    code=str(d.get("code", "")) or None,
                ))
            except Exception:
                logger.warning("Failed to parse diagnostic: %s", d)
        with self._lock:
            self._diagnostics_cache[uri] = diags

    def _on_log_message(self, params: dict) -> None:
        """处理 window/logMessage 通知。"""
        msg = params.get("message", "")
        msg_type = params.get("type", 3)
        level = logging.DEBUG
        if msg_type == 1:
            level = logging.ERROR
        elif msg_type == 2:
            level = logging.WARNING
        logger.log(level, "[lsp] %s", msg)

    def _stderr_loop(self) -> None:
        """daemon 线程：读取 pyright stderr 并记录日志。"""
        stderr_lines: list[str] = []
        while True:
            try:
                if self._process is None or self._process.stderr is None:
                    break
                if self._process.poll() is not None:
                    break
                line = self._process.stderr.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").strip()
                stderr_lines.append(decoded)
                logger.info("[pyright-stderr] %s", decoded)
            except Exception:
                break
        # 进程退出后输出最后 20 行 stderr 帮助诊断
        if stderr_lines:
            tail = stderr_lines[-20:]
            logger.warning("LSP stderr tail (last %d lines):\n%s", len(tail), "\n".join(tail))

    def _do_initialize(self) -> None:
        """执行 LSP 初始化握手。"""
        # 发送 initialize 请求
        init_params = {
            "processId": None,
            "rootUri": self._root_uri,
            "capabilities": {
                "textDocument": {
                    "synchronization": {
                        "didOpen": True,
                        "didChange": True,
                        "didClose": True,
                        "change": 1,  # full sync
                    },
                    "hover": {"contentFormat": ["markdown", "plaintext"]},
                    "definition": {"linkSupport": False},
                    "references": {},
                    "documentSymbol": {"hierarchicalDocumentSymbolSupport": False},
                    "publishDiagnostics": {"relatedInformation": False},
                },
                "workspace": {
                    "didChangeConfiguration": True,
                    "didChangeWatchedFiles": False,
                },
            },
            "workspaceFolders": [{"uri": self._root_uri, "name": "root"}],
        }

        # 使用同步方式发送（STARTING 阶段无事件循环可用）
        msg_id = self._next_id
        self._next_id += 1
        message = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "initialize",
            "params": init_params,
        }
        self._write_message(message)

        # 等待 initialize 响应（同步读取，因为 reader 线程已启动但 loop 可能未运行）
        response = self._wait_for_response_sync(msg_id, timeout=_LSP_START_TIMEOUT)
        if response is None:
            raise RuntimeError("initialize request timed out")

        # 发送 initialized 通知
        self._notify("initialized", {})

    def _wait_for_response_sync(self, msg_id: int, timeout: float) -> dict | None:
        """在 STARTING 阶段同步等待特定 id 的响应。

        直接从 stdout 读取并解析消息，绕过 reader 线程。
        """
        import time as _time
        start = _time.monotonic()
        while _time.monotonic() - start < timeout:
            if self._process is None or self._process.poll() is not None:
                return None
            msg = self._read_message()
            if msg is None:
                continue
            if msg.get("id") == msg_id and ("result" in msg or "error" in msg):
                return msg
            # 如果是通知，交给 dispatch 处理
            if "method" in msg:
                self._dispatch_message(msg)
        return None

    def _do_sanity_check(self) -> None:
        """对根目录中首个 .py 文件发 documentSymbol 请求验证 LSP 可用。"""
        if self._root_path is None:
            return
        # 找到根目录下第一个 .py 文件
        test_file: Path | None = None
        for p in self._root_path.rglob("*.py"):
            test_file = p
            break
        if test_file is None:
            # 没有 .py 文件，跳过 sanity check
            logger.info("LSP sanity check skipped: no .py files in workspace")
            return
        test_uri = test_file.as_uri()

        # 发送 didOpen 通知
        try:
            content = test_file.read_text(encoding="utf-8")
        except Exception:
            content = ""
        self._notify("textDocument/didOpen", {
            "textDocument": {
                "uri": test_uri,
                "languageId": "python",
                "version": 1,
                "text": content,
            },
        })

        # 发送 documentSymbol 请求
        msg_id = self._next_id
        self._next_id += 1
        message = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "textDocument/documentSymbol",
            "params": {"textDocument": {"uri": test_uri}},
        }
        self._write_message(message)

        # 等待响应（10s 超时）
        response = self._wait_for_response_sync(msg_id, timeout=10.0)
        if response is None:
            raise RuntimeError("sanity check documentSymbol request timed out")
        if "error" in response:
            raise RuntimeError(f"sanity check error: {response['error']}")
        # 响应可以为空列表（文件无符号），不强制非空

    def _kill_existing(self) -> bool:
        """终止当前 pyright 进程。返回是否确实杀死了进程。"""
        if self._process is None:
            return False
        from system.sandbox import _kill_proc_tree
        try:
            _kill_proc_tree(self._process.pid)
            try:
                self._process.wait(timeout=_KILL_WAIT_TIMEOUT)
            except subprocess.TimeoutExpired:
                logger.warning("pyright process %d did not exit within %ds", self._process.pid, _KILL_WAIT_TIMEOUT)
        except Exception as exc:
            logger.warning("Failed to kill pyright process: %s", exc)
        killed = self._process.poll() is not None
        self._process = None
        self._root_path = None
        self._root_uri = None
        return killed

    # -- LSP 响应转换 ----------------------------------------------

    def _location_to_reference(self, loc: dict, sandbox: Sandbox) -> LSPReference | None:
        uri = loc.get("uri", "")
        rng = loc.get("range", {})
        start = rng.get("start", {})
        end = rng.get("end", {})
        logical = self._uri_to_logical(uri, sandbox)
        if logical is None:
            return None
        # 读取匹配行文本
        preview = ""
        try:
            content = sandbox.read(logical, offset=start.get("line", 0), limit=1)
            preview = content.strip()
        except Exception:
            pass
        return LSPReference(
            file=logical,
            line=start.get("line", 0) + 1,
            column=start.get("character", 0) + 1,
            end_line=end.get("line", 0) + 1,
            end_column=end.get("character", 0) + 1,
            preview=preview,
        )

    def _location_to_definition(self, loc: dict, sandbox: Sandbox) -> LSPDefinition | None:
        # LocationLink 格式有 targetUri/targetRange；Location 格式有 uri/range
        uri = loc.get("uri") or loc.get("targetUri", "")
        rng = loc.get("range") or loc.get("targetRange", {})
        start = rng.get("start", {})
        end = rng.get("end", {})
        logical = self._uri_to_logical(uri, sandbox)
        preview = ""
        if logical is not None:
            try:
                content = sandbox.read(logical, offset=start.get("line", 0), limit=1)
                preview = content.strip()
            except Exception:
                pass
        return LSPDefinition(
            file=logical,
            line=start.get("line", 0) + 1,
            column=start.get("character", 0) + 1,
            end_line=end.get("line", 0) + 1,
            end_column=end.get("character", 0) + 1,
            preview=preview,
        )

    def _to_symbol(self, s: dict) -> LSPSymbol:
        # documentSymbol 格式
        rng = s.get("range", {})
        start = rng.get("start", {})
        end = rng.get("end", {})
        kind_num = s.get("kind", 13)
        children_raw = s.get("children", [])
        children = [self._to_symbol(c) for c in children_raw if isinstance(c, dict)]
        return LSPSymbol(
            name=s.get("name", ""),
            kind=_SYMBOL_KIND_MAP.get(kind_num, "Unknown"),
            line=start.get("line", 0) + 1,
            column=start.get("character", 0) + 1,
            end_line=end.get("line", 0) + 1,
            end_column=end.get("character", 0) + 1,
            detail=s.get("detail"),
            children=children,
        )


# ---------------------------------------------------------------------------
# 模块级单例
# ---------------------------------------------------------------------------

_lsp_manager: LSPManager | None = None


def get_lsp_manager() -> LSPManager:
    global _lsp_manager
    if _lsp_manager is None:
        _lsp_manager = LSPManager()
    return _lsp_manager


def cleanup_lsp() -> int:
    """强制清理 LSP 进程。供 main.py 在 agent 关闭时调用。返回 killed count。"""
    global _lsp_manager
    if _lsp_manager is None:
        return 0
    return _lsp_manager.cleanup()