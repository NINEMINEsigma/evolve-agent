import asyncio
import threading
import time
import unittest
from unittest.mock import patch

from system import shell_manager


class _FakePty:
    def __init__(self) -> None:
        self.read_started = threading.Event()
        self.closed = threading.Event()
        self.writes: list[str] = []
        self.interrupts = 0
        self.close_calls = 0
        self.exitstatus = 7

    def read(self) -> str:
        self.read_started.set()
        self.closed.wait(2)
        raise EOFError

    def write(self, text: str) -> None:
        if self.closed.is_set():
            raise EOFError
        self.writes.append(text)

    def sendintr(self) -> None:
        if self.closed.is_set():
            raise EOFError
        self.interrupts += 1

    def close(self, force: bool = False) -> None:
        self.close_calls += 1
        self.closed.set()

    def isalive(self) -> bool:
        return not self.closed.is_set()

    def eof(self) -> bool:
        return self.closed.is_set()


class ShellManagerNativeAccessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.pty = _FakePty()
        self.state = shell_manager._ShellSession(
            shell_id="test-shell",
            pty=self.pty,
            pid=None,
            session_id="session",
            character_name="main-agent",
            shell_type="cmd",
            cwd=".",
            event_loop=self.loop,
        )
        self.manager = shell_manager.ShellManager.__new__(shell_manager.ShellManager)

    def tearDown(self) -> None:
        self.loop.close()

    def test_write_and_interrupt_use_native_lifecycle_boundary(self) -> None:
        self.manager._write_line_blocking(self.state, "echo hello")
        self.manager._send_interrupt_blocking(self.state)

        self.assertEqual(self.pty.writes, ["echo hello\r"])
        self.assertEqual(self.pty.interrupts, 1)

        self.state.native_closed.set()
        with self.assertRaises(EOFError):
            self.manager._write_line_blocking(self.state, "after-close")
        with self.assertRaises(EOFError):
            self.manager._send_interrupt_blocking(self.state)

    def test_stop_waits_for_reader_before_closing_pty(self) -> None:
        reader = threading.Thread(
            target=self.manager._reader_loop,
            args=(self.state,),
            daemon=True,
        )
        self.state.reader_thread = reader
        reader.start()
        self.assertTrue(self.pty.read_started.wait(1))

        with patch.object(shell_manager, "SHELL_STOP_WAIT_SECONDS", 0.01):
            self.manager._stop_state_blocking(self.state)

        self.assertTrue(self.state.reader_exited.wait(1))
        self.assertTrue(self.state.native_closed.is_set())
        self.assertEqual(self.pty.close_calls, 1)
        self.assertFalse(self.state.running)

    def test_pty_queries_stop_after_native_close(self) -> None:
        self.assertTrue(self.manager._pty_is_alive(self.state))
        self.assertFalse(self.manager._pty_is_eof(self.state))
        self.state.native_closed.set()
        self.assertFalse(self.manager._pty_is_alive(self.state))
        self.assertTrue(self.manager._pty_is_eof(self.state))


if __name__ == "__main__":
    unittest.main()
