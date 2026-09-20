import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from entity.messages import CharacterConversationMessage, History
from entity.puretype import LLMProfileData, LLMProfilePayload, LLMResponse, Role
from system.context import RuntimeContext
from system.llm_profile_store import LLMProfileStore
from system.session_metadata import (
    MetadataGenerationError,
    MetadataProfileUnavailableError,
    SessionMetadataService,
)
from system.session_store import SessionStore


class SessionMetadataServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        agentspace = root / "agentspace"
        agentspace.mkdir(parents=True)
        self.context = RuntimeContext(
            workspace=root,
            agentspace=agentspace,
            fork_path=root / "fork",
            log_path=root / "test.log",
        )
        self.store = LLMProfileStore(agentspace)
        self.service = SessionMetadataService(
            self.context,
            self.store,
            self.store._lock,
        )
        self.sessions = SessionStore(root / "sessions")
        self.profile_a = self.store.create_profile(self._payload("a", "model-a"))
        self.profile_b = self.store.create_profile(self._payload("b", "model-b"))
        self._write_history("s1", "讨论元数据模型")
        self._write_history("s2", "讨论会话旋转")
        self.sessions.write_active_profile_name("s1", "a")
        self.sessions.write_active_profile_name("s2", "b")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @staticmethod
    def _payload(name: str, model: str) -> LLMProfilePayload:
        return LLMProfilePayload(
            name=name,
            llm_client_name="openai_client",
            base_url="https://example.invalid/v1",
            model=model,
            api_key="secret",
            temperature=0.2,
            max_output_tokens=512,
            reasoning_effort="",
            max_context_tokens=4096,
            vision_image_profile=None,
            audio_profile=None,
            vision_video_profile=None,
            soul_file="SOUL.md",
        )

    def _write_history(self, session_id: str, content: str) -> None:
        history = History()
        history.add_message(CharacterConversationMessage(
            role=Role.USER,
            character_name="end-user",
            content=content,
        ))
        self.sessions.write_history(session_id, history)

    def test_global_profile_precedes_target_session_pointer(self) -> None:
        self.service.select_profile(self.profile_b)
        snapshot = self.service._resolve_profile_snapshot("s1")
        self.assertEqual(snapshot.name, "b")
        self.assertIsNot(snapshot, self.profile_b)

    def test_unconfigured_service_resolves_each_target_pointer(self) -> None:
        self.assertEqual(self.service._resolve_profile_snapshot("s1").name, "a")
        self.assertEqual(self.service._resolve_profile_snapshot("s2").name, "b")

    def test_selected_invalid_profile_does_not_fall_back(self) -> None:
        self.store.set_metadata_profile(self.profile_a)
        self.profile_a.base_url = ""
        with self.assertRaises(MetadataProfileUnavailableError):
            self.service._resolve_profile_snapshot("s2")

    async def test_profile_snapshot_survives_hot_switch(self) -> None:
        self.service.select_profile(self.profile_a)
        snapshot = self.service._resolve_profile_snapshot("s1")
        self.service.select_profile(self.profile_b)
        self.profile_a.model = "edited-after-snapshot"
        self.assertEqual(snapshot.model, "model-a")
        self.assertEqual(self.service._resolve_profile_snapshot("s1").model, "model-b")

    async def test_title_tags_and_summary_parsing(self) -> None:
        client = AsyncMock()
        client.chat.side_effect = [
            LLMResponse(content='"元数据配置"'),
            LLMResponse(content='{"tags":["配置","摘要"]}'),
            LLMResponse(content="Summary: 会话摘要"),
        ]
        with patch("system.session_metadata.create_llm_client", return_value=client):
            self.assertEqual(await self.service.generate_title("s1"), "元数据配置")
            self.assertEqual(
                await self.service.generate_tags("s1", []),
                ["配置", "摘要"],
            )
            self.assertEqual(await self.service.generate_summary("s1"), "会话摘要")

    async def test_ensure_summary_reuses_existing_and_persists_missing(self) -> None:
        self.sessions.write_summary("s1", "已有摘要")
        with patch.object(self.service, "regenerate_summary", new_callable=AsyncMock) as regenerate:
            self.assertEqual(await self.service.ensure_summary("s1"), "已有摘要")
            regenerate.assert_not_awaited()

        with patch.object(
            self.service,
            "generate_summary",
            new=AsyncMock(return_value="新摘要"),
        ):
            self.assertEqual(await self.service.ensure_summary("s2"), "新摘要")
        self.assertEqual(self.sessions.read_summary("s2"), "新摘要")

    async def test_failed_regeneration_preserves_existing_summary(self) -> None:
        self.sessions.write_summary("s1", "旧摘要")
        with patch.object(
            self.service,
            "generate_summary",
            new=AsyncMock(side_effect=MetadataGenerationError("provider failed")),
        ):
            with self.assertRaises(MetadataGenerationError):
                await self.service.regenerate_summary("s1")
        self.assertEqual(self.sessions.read_summary("s1"), "旧摘要")

    def test_root_default_keeps_metadata_reference_optional(self) -> None:
        root = LLMProfileData.model_validate({"profiles": [], "approval_profile": None})
        self.assertIsNone(root.metadata_profile)


if __name__ == "__main__":
    unittest.main()
