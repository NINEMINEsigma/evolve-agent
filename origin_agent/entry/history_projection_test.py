import unittest

from entity.messages import (
    CharacterConversationMessage,
    FunctionCall,
    ImageBlock,
    TextBlock,
    ToolCall,
    ToolResultMessage,
)
from entity.puretype import Role, SessionHistoryRowKind
from entry.agent_support.multimodal import extract_tool_call_meta
from entry.history_projection import (
    history_row_id,
    project_history_content_rows,
    project_history_resources,
    project_history_skeleton,
)


class HistoryProjectionTests(unittest.TestCase):
    def test_message_and_tool_call_rows_share_stable_indices(self) -> None:
        message = CharacterConversationMessage(
            role=Role.ASSISTANT,
            character_name="main-agent",
            content="working",
            tool_calls=[
                ToolCall(id="a", function=FunctionCall(name="Read", arguments='{"path":"ws:a"}')),
                ToolCall(id="b", function=FunctionCall(name="Write", arguments="not-json")),
            ],
        )
        skeleton = project_history_skeleton([message], "main-agent")
        self.assertEqual(
            [row.row_id for row in skeleton],
            ["history:0:message", "history:0:tool:0", "history:0:tool:1"],
        )
        content = project_history_content_rows([message], 0, 1, "main-agent")
        self.assertEqual([row.row_id for row in content], [row.row_id for row in skeleton])
        self.assertEqual(content[1].tool_card.request_args, {"path": "ws:a"})
        self.assertEqual(content[2].tool_card.request_args, {})
        self.assertEqual(content[2].tool_card.request_args_raw, "not-json")

    def test_tool_results_are_embedded_by_tool_call_id(self) -> None:
        assistant = CharacterConversationMessage(
            role=Role.ASSISTANT,
            character_name="main-agent",
            content="",
            tool_calls=[ToolCall(id="a", function=FunctionCall(name="Read", arguments='{"path":"ws:a"}'))],
        )
        result = ToolResultMessage(
            role=Role.TOOL,
            character_name="main-agent",
            tool_call_id="a",
            content={"type": "file", "content": "1: hello"},
        )
        rows = project_history_content_rows([assistant, result], 0, 2, "main-agent")
        self.assertEqual([row.row_id for row in rows], ["history:0:tool:0"])
        self.assertEqual(rows[0].tool_card.status.value, "succeeded")
        self.assertEqual(rows[0].tool_card.result_history_index, 1)

    def test_tool_result_without_request_remains_visible(self) -> None:
        result = ToolResultMessage(
            role=Role.TOOL,
            character_name="main-agent",
            tool_call_id="missing",
            content={"error": "orphan"},
        )
        rows = project_history_content_rows([result], 0, 1, "main-agent")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].row_kind, SessionHistoryRowKind.message)


        message = CharacterConversationMessage(
            role=Role.USER,
            character_name="end-user",
            content=[TextBlock(text="hello"), ImageBlock(image_url="data:image/png;base64,secret")],
        )
        row = project_history_skeleton([message], "main-agent")[0]
        dumped = row.model_dump_json()
        self.assertNotIn("hello", dumped)
        self.assertNotIn("secret", dumped)

    def test_resources_are_deduplicated(self) -> None:
        messages = [
            CharacterConversationMessage(
                role=Role.ASSISTANT,
                character_name="main-agent",
                content="![a](/files/ws/a.png) ![again](/files/ws/a.png)",
            ),
            ToolResultMessage(
                role=Role.TOOL,
                character_name="main-agent",
                tool_call_id="x",
                content={
                    "markdown": "![b](/files/ws/b.png)",
                    "download_url": "/downloads/ws/result.txt",
                    "filename": "result.txt",
                    "size": 12,
                },
            ),
        ]
        resources = project_history_resources(messages, "session")
        self.assertEqual([item.url for item in resources.images], ["/files/ws/a.png", "/files/ws/b.png"])
        self.assertEqual(len(resources.downloads), 1)

    def test_tool_meta_extraction_is_type_safe(self) -> None:
        self.assertEqual(extract_tool_call_meta({"_meta": {"duration": 1}}), {"duration": 1})
        self.assertIsNone(extract_tool_call_meta({"_meta": "bad"}))
        self.assertIsNone(extract_tool_call_meta("text"))
        self.assertIsNone(extract_tool_call_meta([TextBlock(text="text")]))

    def test_tool_row_requires_tool_index(self) -> None:
        with self.assertRaises(ValueError):
            history_row_id(0, SessionHistoryRowKind.tool_card)


if __name__ == "__main__":
    unittest.main()
