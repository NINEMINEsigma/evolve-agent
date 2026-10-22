"""Owned-process identity and one-shot tree termination.

Identity is captured from the object held by the creator. A bare PID is never
sufficient, and this module does not scan processes or ports.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from typing import Any

from entity.constant.timeouts import RESOURCE_CLEANUP_POLL_SECONDS
from system.lifecycle import LifecycleFailure


class OwnedProcessIdentity:
    """A process generation whose termination was authorized at creation."""

    def __init__(
        self,
        *,
        pid: int,
        source: Any,
        windows_handle: int | None,
    ) -> None:
        self.pid = pid
        self.source = source
        self.windows_handle = windows_handle
        self.exited = False
        self.kill_started = False
        self.helper: subprocess.Popen[bytes] | None = None
        self._closed = False

    @classmethod
    def from_popen(cls, proc: subprocess.Popen[Any]) -> OwnedProcessIdentity | None:
        """Capture the creator-held Popen handle. No PID-only fallback exists."""
        pid = proc.pid
        if pid is None:
            return None
        if sys.platform == "win32":
            # CPython exposes the original process handle on Popen._handle.
            # This is an explicit external compatibility boundary, not business reflection.
            handle = getattr(proc, "_handle", None)
            if not isinstance(handle, int) or handle == 0:
                return None
            return cls(pid=pid, source=proc, windows_handle=handle)
        return cls(pid=pid, source=proc, windows_handle=None)

    @classmethod
    def from_asyncio(
        cls,
        proc: asyncio.subprocess.Process,
    ) -> OwnedProcessIdentity | None:
        """Capture identity only while the creating loop still holds the process."""
        if proc.pid is None:
            return None
        transport = getattr(proc, "_transport", None)
        raw_process = getattr(transport, "_proc", None) if transport is not None else None
        if isinstance(raw_process, subprocess.Popen):
            return cls.from_popen(raw_process)
        return None

    @classmethod
    def from_shell(cls, state: Any) -> OwnedProcessIdentity | None:
        """Accept only a stable identity already stored by Shell creation."""
        identity = getattr(state, "process_identity", None)
        if isinstance(identity, OwnedProcessIdentity):
            return identity
        return None

    def close(self) -> None:
        """Release only the duplicated identity reference, never the creator handle."""
        self._closed = True

    def still_matches(self) -> bool:
        """Return whether the captured creator object still identifies this generation."""
        if self._closed:
            return False
        source_pid = getattr(self.source, "pid", None)
        return source_pid == self.pid


async def terminate_owned_tree(identity: OwnedProcessIdentity) -> None:
    """Issue one authorized termination and retain the helper until it exits."""
    if identity.kill_started:
        return
    if not identity.still_matches():
        raise LifecycleFailure("Owned process identity no longer matches its source")
    identity.kill_started = True
    if sys.platform == "win32":
        if identity.windows_handle is None:
            raise LifecycleFailure("Windows process termination requires a captured handle")
        helper = subprocess.Popen(
            ["taskkill", "/T", "/F", "/PID", str(identity.pid)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        identity.helper = helper
        while helper.poll() is None:
            await asyncio.sleep(RESOURCE_CLEANUP_POLL_SECONDS)
        if helper.returncode not in (0, 128) and _source_running(identity):
            raise LifecycleFailure("Owned process tree termination failed")
        return
    import os
    import signal

    try:
        os.killpg(os.getpgid(identity.pid), signal.SIGTERM)
    except ProcessLookupError:
        identity.exited = True


def _source_running(identity: OwnedProcessIdentity) -> bool:
    source = identity.source
    if isinstance(source, subprocess.Popen):
        return source.poll() is None
    returncode = getattr(source, "returncode", None)
    return returncode is None
