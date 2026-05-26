"""Path sandbox — the single security boundary for all tool operations.

All file-system tools and subprocess spawns **MUST** route through this
module.  LLM-facing paths are **logical** (``ws:logs/error.log``) and are
resolved to real absolute paths only inside this module.  No tool handler
or subprocess ever sees or accepts a raw filesystem path.

Logical namespaces
    ==============  ===================  ======  ==========================
    Prefix           Maps to              Perm    Purpose
    ==============  ===================  ======  ==========================
    ``fork:``        ctx.fork_path        rw      Read/write evolved code
    ``ws:``          ctx.agentspace       rw      General agent I/O
    ``fix:``         ctx.fix_path         rw      Repair target (fallback)
    ==============  ===================  ======  ==========================

    In **fast** mode ``fork:`` is read+write.
    In **fallback** mode ``fix:`` is read+write.

There is **no** ``self:`` namespace — the agent cannot read or mutate its
own runtime copy.  Evolution happens exclusively through fork:/fix:.

Every path must carry an explicit namespace prefix.  Bare paths, ``..``
traversal, and absolute paths are rejected unconditionally.
"""

from __future__ import annotations

import logging
import subprocess  # nosec
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from system.context import RuntimeContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Permission model
# ---------------------------------------------------------------------------


class Access(str, Enum):
    READ = "read"
    WRITE = "write"


# Map: (mode, namespace) → allowed access
# "fast" mode: fork=rw, ws=rw
# "fallback" mode: fix=rw, ws=rw
# There is NO self: namespace — the agent cannot inspect or mutate its
# own runtime copy.  Evolution happens exclusively through fork:/fix:.
_PERMISSIONS: Dict[str, Dict[str, List[Access]]] = {
    "fast": {
        "fork":  [Access.READ, Access.WRITE],
        "ws":    [Access.READ, Access.WRITE],
    },
    "fallback": {
        "fix":   [Access.READ, Access.WRITE],
        "ws":    [Access.READ, Access.WRITE],
    },
}


class SandboxError(PermissionError):
    """Raised when a tool operation violates sandbox constraints."""


# ---------------------------------------------------------------------------
# Process-tree kill helper
# ---------------------------------------------------------------------------


def _kill_proc_tree(pid: int) -> None:
    """Force-kill a process and all its descendants.

    On Windows uses ``taskkill /T /F``.  On Unix sends SIGTERM to the
    process group.
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
    """Result of resolving a logical path through the sandbox."""

    model_config = ConfigDict(frozen=True)

    logical: str   # e.g. "ws:data/config.json"
    real: Path      # absolute path on disk
    namespace: str  # "fork" | "ws" | "fix"


class Sandbox:
    """Stateless security boundary.  Created once per RuntimeContext.

    Usage::

        sandbox = Sandbox(ctx)
        r = sandbox.resolve("ws:logs/error.log", Access.READ)
        content = r.real.read_text()

        r = sandbox.resolve("fork:main.py", Access.WRITE)
        r.real.write_text(new_code)

        sandbox.run(["python", "-m", "pytest"], cwd_ns="fork:")
    """

    def __init__(self, ctx: RuntimeContext) -> None:
        self._ctx = ctx

    # -- path resolution ----------------------------------------------------

    def resolve(self, logical: str, access: Access) -> ResolvedPath:
        """Parse a logical path, check permissions, return absolute real path.

        Raises ``SandboxError`` on any violation.
        """
        if not logical or not isinstance(logical, str):
            raise SandboxError("logical path must be a non-empty string")

        # ---- extract namespace prefix ----
        if ":" in logical:
            ns, rest = logical.split(":", 1)
        else:
            raise SandboxError(
                f"Path must carry a namespace prefix "
                f"(fork:, ws:, fix:). Got: {logical!r}"
            )

        ns = ns.strip()
        if ns not in _PERMISSIONS.get(self._ctx.mode, {}):
            raise SandboxError(
                f"Unknown namespace '{ns}:' in mode '{self._ctx.mode}'. "
                f"Allowed: {list(_PERMISSIONS.get(self._ctx.mode, {}).keys())}"
            )

        rest = rest.lstrip("/")

        # ---- path-traversal check ----
        if ".." in rest.split("/") or rest.startswith("/"):
            raise SandboxError(
                f"Path traversal rejected: {logical!r}"
            )

        # ---- resolve to real directory ----
        ns_map = {
            "fork": self._ctx.fork_path,
            "ws":   self._ctx.agentspace,
            "fix":  self._ctx.fix_path,
        }
        base = ns_map[ns]
        if base is None:
            raise SandboxError(
                f"Namespace '{ns}:' is not available in mode '{self._ctx.mode}'"
            )

        real = (base / rest).resolve()

        # ---- enforce that resolved path stays under base ----
        try:
            real.relative_to(base)
        except ValueError:
            raise SandboxError(
                f"Resolved path {real} escapes namespace base {base}"
            )

        # ---- permission check ----
        allowed = _PERMISSIONS[self._ctx.mode][ns]
        if access not in allowed:
            raise SandboxError(
                f"Access {access.value} denied for namespace '{ns}:' "
                f"in mode '{self._ctx.mode}'. Allowed: "
                f"{[a.value for a in allowed]}"
            )

        return ResolvedPath(logical=logical, real=real, namespace=ns)

    def resolve_read(self, logical: str) -> ResolvedPath:
        return self.resolve(logical, Access.READ)

    def resolve_write(self, logical: str) -> ResolvedPath:
        return self.resolve(logical, Access.WRITE)

    # -- subprocess (also sandboxed) ----------------------------------------

    # Commands that tools are allowed to execute (by basename).
    _ALLOWED_COMMANDS: frozenset[str] = frozenset({
        "python", "python3", "pip", "pnpm", "git", "cmd", "curl"
    })

    @property
    def allowed_commands(self) -> frozenset[str]:
        """Public read-only access to the command allowlist."""
        return self._ALLOWED_COMMANDS

    def run(
        self,
        args: List[str],
        *,
        cwd_ns: str = "ws:",
        timeout: int = 30,
        extra_env: Dict[str, str] | None = None,
        encoding: str = "utf-8",
        errors: str | None = None,
    ) -> subprocess.CompletedProcess:
        """Run a subprocess with sandboxed working directory.

        *args* — command + arguments.  The command basename must be in the
        allowed list.

        *cwd_ns* — logical working directory for the subprocess.

        *encoding* — text encoding for subprocess output (default ``"utf-8"``).
        *errors* — error-handling scheme for decode errors (e.g. ``"replace"``).

        Raises ``SandboxError`` if the command is not allowed or paths
        escape the sandbox.
        """
        if not args:
            raise SandboxError("subprocess args must not be empty")

        # -- validate command --
        cmd = args[0]
        cmd_name = Path(cmd).name
        if cmd_name not in self._ALLOWED_COMMANDS:
            raise SandboxError(
                f"Command '{cmd_name}' is not in the allowed list: "
                f"{sorted(self._ALLOWED_COMMANDS)}"
            )

        # -- validate cwd --
        cwd_r = self.resolve(cwd_ns, Access.READ)
        if not cwd_r.real.is_dir():
            raise SandboxError(f"cwd does not exist or is not a directory: {cwd_ns}")

        # -- validate any path arguments that look like logical paths --
        for arg in args:
            if ":" in arg and any(arg.startswith(p) for p in ("ws:", "fork:", "fix:")):
                raise SandboxError(
                    f"Path arguments to subprocess commands must be resolved "
                    f"by the tool handler before calling sandbox.run(). "
                    f"Got: {arg!r}"
                )

        # -- build env --
        env = None
        if extra_env:
            import os
            env = os.environ.copy()
            env.update(extra_env)

        kwargs: dict = dict(
            encoding=encoding,
        )
        if errors is not None:
            kwargs["errors"] = errors

        logger.debug("sandbox.run | cwd=%s cmd=%s", cwd_r.real, args)

        # Use Popen so we can force-kill the entire process tree on timeout.
        # subprocess.run(timeout=...) does not reliably terminate child
        # processes (e.g. pnpm spawning node processes) on Windows.
        import os as _os
        popen_kwargs: dict = {
            "cwd": str(cwd_r.real),
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "env": env,
        }
        if sys.platform == "win32":
            # CREATE_NEW_PROCESS_GROUP allows sending CTRL_BREAK_EVENT,
            # but we will use taskkill for a more reliable tree kill.
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        proc = subprocess.Popen(args, **popen_kwargs, **kwargs)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_proc_tree(proc.pid)
            stdout, stderr = "", ""
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            raise subprocess.TimeoutExpired(
                cmd=args[0], timeout=timeout, output=stdout, stderr=stderr,
            )

        return subprocess.CompletedProcess(
            args=args,
            returncode=proc.returncode,
            stdout=stdout,
            stderr=stderr,
        )

    # -- helpers for tools --------------------------------------------------

    def read(self, logical: str, offset: int = 0, limit: int = 100) -> str:
        """Read file content through the sandbox with line-based pagination.

        offset: 0-indexed line number to start from (default 0).
        limit:  max lines to return (default 100).  Pass 0 to read the
                entire file without truncation.
        """
        r = self.resolve_read(logical)
        try:
            content = r.real.read_text(encoding="utf-8")
            if limit > 0 and (offset > 0 or limit < len(content.splitlines())):
                lines = content.splitlines()
                chunk = lines[offset:offset + limit]
                return "\n".join(chunk)
            return content
        except FileNotFoundError:
            raise SandboxError(f"File not found: {logical}")

    def write(self, logical: str, content: str) -> None:
        """Write file content through the sandbox."""
        r = self.resolve_write(logical)
        r.real.parent.mkdir(parents=True, exist_ok=True)
        r.real.write_text(content, encoding="utf-8")

    def exists(self, logical: str) -> bool:
        """Check if a logical path exists (read-only check)."""
        try:
            r = self.resolve_read(logical)
            return r.real.exists()
        except SandboxError:
            return False

    def list_dir(self, logical: str) -> List[str]:
        """List directory entries (read-only check)."""
        r = self.resolve_read(logical)
        if not r.real.is_dir():
            raise SandboxError(f"Not a directory: {logical}")
        return sorted(
            p.name for p in r.real.iterdir()
        )

    def delete(self, logical: str) -> None:
        """Delete a file or empty directory (write check)."""
        r = self.resolve_write(logical)
        if r.real.is_dir():
            r.real.rmdir()
        else:
            r.real.unlink(missing_ok=True)