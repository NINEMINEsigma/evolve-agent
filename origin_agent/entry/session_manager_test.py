import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from entity.messages import CharacterConversationMessage, History
from entity.puretype import Loop, Role, SessionInfo
from entry.session_manager import LoopSessionManager, terminate_and_rotate_session
from system.session_metadata import MetadataGenerationError
from system.session_store import SessionStore


class _FakeGatewaySessionManager:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.archived: list[tuple[str, str | None]] = []
        self.removed: list[str] = []
        self.tags: list[tuple[str, list[str]]] = []

    def get(self, session_id: str):
        return SessionInfo(id=session_id, loop_type=Loop.parent)

    def get_all_tags(self) -> list[str]:
        return []

    def set_session_tags(self, session_id: str, tags: list[str]) -> None:
        self.tags.append((session_id, tags))

    def create_with_context(self, *args, **kwargs) -> str:
        self.created.append("new")
        return "new"

    def archive(self, session_id: str, continuation_sid: str | None = None) -> None:
        self.archived.append((session_id, continuation_sid))

    def remove(self, session_id: str) -> None:
        self.removed.append(session_id)


class _FakeLoop:
    def __init__(self, store: SessionStore, manager, metadata_service) -> None:
        self.session_id = "old"
        self.session_store = store
        self.session_manager = manager
        self.history = History()
        self.last_prompt_tokens = 100
        self.current_character_agent = "main-agent"
        self.app = SimpleNamespace(
            session_metadata_service=metadata_service,
            shell_manager=SimpleNamespace(stop_session=AsyncMock()),
        )
        self.saved: list[str] = []

    def save_history(self, session_id: str) -> None:
        self.saved.append(session_id)
        self.session_store.write_history(session_id, self.history)

    def load_history(self, history: History) -> None:
        self.history = history


class SessionLifecycleMetadataTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = SessionStore(Path(self.tempdir.name) / "sessions")
        self.manager = _FakeGatewaySessionManager()
        self.metadata = SimpleNamespace(
            ensure_summary=AsyncMock(return_value="摘要"),
            generate_tags=AsyncMock(return_value=["摘要"]),
        )
        self.old_history = History()
        self.old_history.add_message(CharacterConversationMessage(
            role=Role.USER,
            character_name="end-user",
            content="旧消息",
        ))
        self.store.write_history("old", self.old_history)
        self.store.write_active_profile_name("old", "profile")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    async def test_rotation_summary_failure_has_no_commit_side_effect(self) -> None:
        self.metadata.ensure_summary.side_effect = MetadataGenerationError("failed")
        with self.assertRaises(MetadataGenerationError):
            await terminate_and_rotate_session(
                session_id="old",
                session_store=self.store,
                session_manager=self.manager,
                metadata_service=self.metadata,
                current_character_agent="main-agent",
            )
        self.assertEqual(self.manager.created, [])
        self.assertEqual(self.manager.archived, [])

    async def test_incomplete_continuation_is_removed_before_old_archive(self) -> None:
        original_write = self.store.write_history

        def fail_new_history(session_id: str, history: History) -> None:
            if session_id == "new":
                raise OSError("disk full")
            original_write(session_id, history)

        self.store.write_history = fail_new_history  # type: ignore[method-assign]
        with self.assertRaises(MetadataGenerationError):
            await terminate_and_rotate_session(
                session_id="old",
                session_store=self.store,
                session_manager=self.manager,
                metadata_service=self.metadata,
                current_character_agent="main-agent",
            )
        self.assertEqual(self.manager.removed, ["new"])
        self.assertEqual(self.manager.archived, [])

    async def test_manual_termination_archives_with_metadata_warnings(self) -> None:
        self.metadata.ensure_summary.side_effect = MetadataGenerationError("summary")
        self.metadata.generate_tags.side_effect = MetadataGenerationError("tags")
        loop = _FakeLoop(self.store, self.manager, self.metadata)
        lifecycle = LoopSessionManager(loop)  # type: ignore[arg-type]

        result = await lifecycle.terminate_session()

        self.assertTrue(result.terminated)
        self.assertEqual(len(result.metadata_warnings), 2)
        self.assertEqual(self.manager.archived, [("old", None)])

    async def test_failed_rotation_restores_complete_user_message(self) -> None:
        self.metadata.ensure_summary.side_effect = MetadataGenerationError("summary")
        loop = _FakeLoop(self.store, self.manager, self.metadata)
        trigger = CharacterConversationMessage(
            role=Role.USER,
            character_name="end-user",
            content="触发消息",
            visible_characters=["main-agent"],
            response_characters=["main-agent"],
            message_suffix="fixed",
            dynamic_message_suffix="dynamic",
        )
        loop.history.add_message(trigger)
        loop.save_history("old")
        lifecycle = LoopSessionManager(loop)  # type: ignore[arg-type]

        with self.assertRaises(MetadataGenerationError):
            await lifecycle.rotate_session_for_continuation(
                "old",
                move_last_user_message=True,
            )

        restored = loop.history.get_message(loop.history.count - 1)
        self.assertIs(restored, trigger)
        self.assertEqual(restored.message_suffix, "fixed")
        self.assertEqual(restored.dynamic_message_suffix, "dynamic")

    async def test_successful_rotation_archives_only_after_history_write(self) -> None:
        await terminate_and_rotate_session(
            session_id="old",
            session_store=self.store,
            session_manager=self.manager,
            metadata_service=self.metadata,
            current_character_agent="main-agent",
        )
        self.assertEqual(self.manager.archived, [("old", "new")])
        self.assertIsNotNone(self.store.read_history("new"))


if __name__ == "__main__":
    unittest.main()
