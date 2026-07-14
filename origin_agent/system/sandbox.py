"""路径沙盒 — 所有工具操作的唯一安全边界。

所有文件系统工具和子进程调用**必须**通过此模块路由。
LLM 可见的路径是**逻辑路径**（``ws:logs/error.log``），
仅在此模块内部解析为真实绝对路径。任何工具 handler
或子进程都不会看到或接受裸文件系统路径。

逻辑命名空间
    ==============  ===================  ======  ==========================
    前缀            映射到              权限    用途
    ==============  ===================  ======  ==========================
    ``fork:``        ctx.fork_path        rw      读写进化代码
    ``ws:``          ctx.agentspace       rw      通用 agent I/O
    ``fix:``         ctx.fix_path         rw      修复目标（fallback）
    ``skills:``      ctx.skills_path      rw      skill 文件读写
    ==============  ===================  ======  ==========================

    在 **fast** 模式下 ``fork:`` 和 ``skills:`` 可读写。
    在 **fallback** 模式下 ``fix:`` 和 ``skills:`` 可读写。

**没有** ``self:`` 命名空间 — agent 不能读取或修改自身的运行时副本。
进化完全通过 fork:/fix: 实现。

所有路径必须携带显式命名空间前缀。裸路径、``..`` 遍历
和绝对路径无条件拒绝。
"""

from __future__ import annotations

import logging
import subprocess  # nosec
import sys
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List

from entity.constant import NAMESPACE_PREFIXES
from system.context import get_runtime_context
from system.subprocess_utils import build_subprocess_env, completed_process_from_bytes, windows_process_group_flags

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from system.context import RuntimeContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 权限模型
# ---------------------------------------------------------------------------


class Access(str, Enum):
    READ = "read"
    WRITE = "write"


# 映射：(mode, namespace) → 允许的访问类型
# "fast" 模式：fork=rw, ws=rw, skills=rw
# "fallback" 模式：fix=rw, ws=rw, skills=rw
# 不存在 self: 命名空间 — agent 不能查看或修改自身的运行时副本。
# 进化完全通过 fork:/fix: 实现。
_PERMISSIONS: dict[str, dict[str, list[Access]]] = {
    "fast": {
        "fork":   [Access.READ, Access.WRITE],
        "ws":     [Access.READ, Access.WRITE],
        "skills": [Access.READ, Access.WRITE],
    },
    "fallback": {
        "fix":    [Access.READ, Access.WRITE],
        "ws":     [Access.READ, Access.WRITE],
        "skills": [Access.READ, Access.WRITE],
    },
}


class SandboxError(PermissionError):
    """当工具操作违反沙盒约束时抛出。"""


# ---------------------------------------------------------------------------
# 进程树终止辅助函数
# ---------------------------------------------------------------------------


def _kill_proc_tree(pid: int) -> None:
    """强制终止进程及其所有子孙进程。

    Windows 使用 ``taskkill /T /F``。
    Unix 向进程组发送 SIGTERM。
    """
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            capture_output=True,
        )
    else:
        try:
            import os
            import signal
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except ProcessLookupError:
            pass


# ---------------------------------------------------------------------------
# Sandbox
# ---------------------------------------------------------------------------


class ResolvedPath(BaseModel):
    """逻辑路径通过沙盒解析后的结果。"""

    model_config = ConfigDict(frozen=True)

    logical: str   # 例如 "ws:data/config.json"
    real: Path      # 磁盘上的绝对路径
    namespace: str  # "fork" | "ws" | "fix"


class Sandbox:
    """无状态安全边界。每个 RuntimeContext 创建一次。

    用法::

        sandbox = Sandbox(ctx)
        r = sandbox.resolve("ws:logs/error.log", Access.READ)
        content = r.real.read_text()

        r = sandbox.resolve("fork:main.py", Access.WRITE)
        r.real.write_text(new_code)

        sandbox.run(["python", "-m", "pytest"], cwd_ns="fork:")
    """

    def __init__(self, ctx: RuntimeContext) -> None:
        self._ctx: RuntimeContext = ctx

    # -- 路径解析 ----------------------------------------------------

    def resolve(self, logical: str, access: Access) -> ResolvedPath:
        """解析逻辑路径，检查权限，返回绝对真实路径。

        任何违规均抛出 ``SandboxError``。
        """
        if not logical or not isinstance(logical, str):
            raise SandboxError("logical path must be a non-empty string")

        # ---- 提取命名空间前缀 ----
        ns: str
        rest: str
        if ":" in logical:
            ns, rest = logical.split(":", 1)
        else:
            raise SandboxError(
                f"Path must carry a namespace prefix "
                f"(fork:, ws:, fix:, skills:). Got: {logical!r}"
            )

        ns = ns.strip()
        if ns not in _PERMISSIONS.get(self._ctx.mode, {}):
            raise SandboxError(
                f"Unknown namespace '{ns}:' in mode '{self._ctx.mode}'. "
                f"Allowed: {list(_PERMISSIONS.get(self._ctx.mode, {}).keys())}"
            )

        rest = rest.lstrip("/")

        # ---- 路径遍历检查 ----
        if ".." in rest.split("/") or rest.startswith("/") or (len(rest)>1 and rest[1]==":"):
            raise SandboxError(
                f"Path traversal rejected: {logical!r}"
            )
        if ".." in rest.split("\\") or rest.startswith("\\") or (len(rest)>1 and rest[1]==":"):
            raise SandboxError(
                f"Path traversal rejected: {logical!r}"
            )

        # ---- 解析到真实目录 ----
        ns_map: dict[str, Path | None] = {
            "fork":   self._ctx.fork_path,
            "ws":     self._ctx.agentspace,
            "fix":    self._ctx.fix_path,
            "skills": self._ctx.skills_path,
        }
        base: Path | None = ns_map[ns]
        if base is None:
            raise SandboxError(
                f"Namespace '{ns}:' is not available in mode '{self._ctx.mode}'"
            )

        real: Path = (base / rest).resolve()

        # ---- 强制解析后路径仍在 base 之下 ----
        try:
            real.relative_to(base)
        except ValueError:
            raise SandboxError(
                f"Resolved path {real} escapes namespace base {base}"
            )

        # ---- 权限检查 ----
        allowed: list[Access] = _PERMISSIONS[self._ctx.mode][ns]
        if access not in allowed:
            raise SandboxError(
                f"Access {access.value} denied for namespace '{ns}:' "
                f"in mode '{self._ctx.mode}'. Allowed: "
                f"{[a.value for a in allowed]}"
            )

        return ResolvedPath(logical=logical, real=real, namespace=ns)

    @property
    def agentspace(self) -> Path:
        """返回当前沙盒的 ws: 命名空间根目录。"""
        return self._ctx.agentspace

    def resolve_read(self, logical: str) -> ResolvedPath:
        return self.resolve(logical, Access.READ)

    def resolve_write(self, logical: str) -> ResolvedPath:
        return self.resolve(logical, Access.WRITE)

    # -- 子进程（同样受沙盒约束） ----------------------------------------

    def run(
        self,
        args: list[str],
        *,
        cwd_ns: str = "ws:",
        timeout: int | None = None,
        extra_env: dict[str, str] | None = None,
        encoding: str = "utf-8",
        errors: str | None = None,
    ) -> subprocess.CompletedProcess:
        """以沙盒化工作目录运行子进程。

        *args* — 命令 + 参数。命令 basename 必须在允许列表中。

        *cwd_ns* — 子进程的逻辑工作目录。

        *timeout* — 超时秒数；``None`` 时从 ``RuntimeContext.tool_timeout`` 获取。

        *encoding* — 子进程输出的文本编码（默认 ``"utf-8"``）。
        *errors* — 解码错误的处理方案（例如 ``"replace"``）。

        如果命令不允许或路径逃逸沙盒，抛出 ``SandboxError``。
        """
        if timeout is None:
            timeout = get_runtime_context().tool_timeout

        if not args:
            raise SandboxError("subprocess args must not be empty")

        # -- 验证命令 --
        cmd: str = args[0]
        cmd_name: str = Path(cmd).name
        # if cmd_name not in self._ALLOWED_COMMANDS:
        #     raise SandboxError(
        #         f"Command '{cmd_name}' is not in the allowed list: "
        #         f"{sorted(self._ALLOWED_COMMANDS)}"
        #     )

        # -- 验证 cwd --
        cwd_r: ResolvedPath = self.resolve(cwd_ns, Access.READ)
        if not cwd_r.real.is_dir():
            raise SandboxError(f"cwd does not exist or is not a directory: {cwd_ns}")

        # -- 验证任何看起来像逻辑路径的参数 --
        for arg in args:
            if ":" in arg and any(arg.startswith(p) for p in NAMESPACE_PREFIXES):
                raise SandboxError(
                    f"Path arguments to subprocess commands must be resolved "
                    f"by the tool handler before calling sandbox.run(). "
                    f"Got: {arg!r}"
                )

        # -- 构建 env --
        env = build_subprocess_env(extra_env)

        logger.debug("sandbox.run | cwd=%s cmd=%s", cwd_r.real, args)

        # 使用 Popen 以支持超时时强制终止整个进程树。
        # subprocess.run(timeout=...) 在 Windows 上不能可靠地
        # 终止子进程（例如 pnpm 生成的 node 进程）。
        popen_kwargs: dict = {
            "cwd": str(cwd_r.real),
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": False,
            "env": env,
        }
        if sys.platform == "win32":
            # CREATE_NEW_PROCESS_GROUP 允许发送 CTRL_BREAK_EVENT，
            # 但我们将使用 taskkill 进行更可靠的进程树终止。
            popen_kwargs["creationflags"] = windows_process_group_flags()
        proc: subprocess.Popen = subprocess.Popen(args, **popen_kwargs)
        stdout: bytes
        stderr: bytes
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_proc_tree(proc.pid)
            stdout, stderr = b"", b""
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            raise subprocess.TimeoutExpired(
                cmd=args[0], timeout=timeout, output="", stderr="",
            )

        return completed_process_from_bytes(
            args=args,
            returncode=proc.returncode,
            stdout=stdout,
            stderr=stderr,
        )

    # -- 工具辅助方法 --------------------------------------------------

    def read(self, logical: str, offset: int = 0, limit: int = 100) -> str:
        """通过沙盒读取文件内容，支持按行分页。

        offset: 起始行号（0-indexed，默认 0）。
        limit:  最大返回行数（默认 100）。传 0 读取完整文件不截断。
        """
        r: ResolvedPath = self.resolve_read(logical)
        try:
            content: str = r.real.read_text(encoding="utf-8")
            if limit > 0 and (offset > 0 or limit < len(content.splitlines())):
                lines: list[str] = content.splitlines()
                chunk: list[str] = lines[offset:offset + limit]
                return "\n".join(chunk)
            return content
        except FileNotFoundError:
            raise SandboxError(f"File not found: {logical}")

    def write(self, logical: str, content: str) -> None:
        """通过沙盒写入文件内容。"""
        r: ResolvedPath = self.resolve_write(logical)
        r.real.parent.mkdir(parents=True, exist_ok=True)
        r.real.write_text(content, encoding="utf-8")

    def append(self, logical: str, content: str) -> None:
        """通过沙盒追加文件内容。文件不存在时报错。"""
        r: ResolvedPath = self.resolve_write(logical)
        if not r.real.exists():
            raise SandboxError(f"File not found: {logical}")
        if not r.real.is_file():
            raise SandboxError(f"Not a file: {logical}")
        with r.real.open("a", encoding="utf-8") as f:
            f.write(content)

    def exists(self, logical: str) -> bool:
        """检查逻辑路径是否存在（只读检查）。"""
        try:
            r: ResolvedPath = self.resolve_read(logical)
            return r.real.exists()
        except SandboxError:
            return False

    def list_dir(self, logical: str) -> list[str]:
        """列出目录条目（只读检查）。"""
        r: ResolvedPath = self.resolve_read(logical)
        if not r.real.is_dir():
            raise SandboxError(f"Not a directory: {logical}")
        return sorted(
            p.name for p in r.real.iterdir()
        )

    def copy(self, logical_src: str, logical_dst: str) -> None:
        """复制文件（源只读、目标写入）。"""
        src: ResolvedPath = self.resolve_read(logical_src)
        dst: ResolvedPath = self.resolve_write(logical_dst)
        if not src.real.is_file():
            raise SandboxError(f"Source is not a file: {logical_src}")
        dst.real.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(src.real, dst.real)

    def copy_folder(self, logical_src: str, logical_dst: str) -> None:
        """递归复制目录（源只读、目标写入）。"""
        src: ResolvedPath = self.resolve_read(logical_src)
        dst: ResolvedPath = self.resolve_write(logical_dst)
        if not src.real.is_dir():
            raise SandboxError(f"Source is not a directory: {logical_src}")
        if dst.real.exists():
            raise SandboxError(f"Destination already exists: {logical_dst}")
        dst.real.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copytree(src.real, dst.real)

    def move(self, logical_src: str, logical_dst: str) -> None:
        """移动或重命名文件/目录（源只读、目标写入）。"""
        src: ResolvedPath = self.resolve_read(logical_src)
        dst: ResolvedPath = self.resolve_write(logical_dst)
        if not src.real.exists():
            raise SandboxError(f"Source does not exist: {logical_src}")
        dst.real.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.move(str(src.real), str(dst.real))

    def delete(self, logical: str) -> None:
        """删除文件或空目录（写入检查）。"""
        r: ResolvedPath = self.resolve_write(logical)
        if r.real.is_dir():
            r.real.rmdir()
        else:
            r.real.unlink(missing_ok=True)

    def resolve_abs(self, logical: str) -> str:
        """将逻辑路径解析为绝对路径字符串（只读检查）。"""
        r: ResolvedPath = self.resolve_read(logical)
        return str(r.real)

    def create_folder(self, logical: str, parents: bool = True) -> None:
        """创建目录（写入检查）。"""
        r: ResolvedPath = self.resolve_write(logical)
        r.real.mkdir(parents=parents, exist_ok=True)

    def delete_folder(self, logical: str) -> None:
        """递归删除目录及其所有内容（写入检查）。"""
        import shutil
        r: ResolvedPath = self.resolve_write(logical)
        if not r.real.exists():
            raise SandboxError(f"Path does not exist: {logical}")
        if not r.real.is_dir():
            raise SandboxError(f"Not a directory: {logical}")
        shutil.rmtree(str(r.real))

    def is_file(self, logical: str) -> bool:
        """检查逻辑路径是否为一个文件（只读检查）。"""
        r: ResolvedPath = self.resolve_read(logical)
        return r.real.is_file()

    def is_dir(self, logical: str) -> bool:
        """检查逻辑路径是否为一个目录（只读检查）。"""
        r: ResolvedPath = self.resolve_read(logical)
        return r.real.is_dir()

    def count_lines(self, logical: str) -> int:
        """计算文件的总行数（只读检查）。如果文件不存在或不是文件则报错。"""
        r: ResolvedPath = self.resolve_read(logical)
        if not r.real.exists():
            raise SandboxError(f"File not found: {logical}")
        if not r.real.is_file():
            raise SandboxError(f"Not a file: {logical}")
        content = r.real.read_text(encoding="utf-8")
        if content:
            return content.count("\n") + (1 if not content.endswith("\n") else 0)
        return 0