"""Main Agent identity refresh tool."""

from __future__ import annotations

from abstract.tools.tool import BaseTool, BaseToolSet, ToolExecution, ToolHandlerResult, tool_result
from entity.constant import SOUL_META_CHARACTER_NAME_KEY
from entity.puretype import ToolAvailability, ToolDangerLevel
from system.application import Application
from system.runtime import RuntimeSystem

_DEFAULT_SOUL_FILE: str = "SOUL.md"

_REFRESH_IDENTITY_SCHEMA = {
    "description": """Refresh the running main Agent's character name from its SOUL metadata file.

## Effect
- Reads ``ws:SOUL.md.meta`` and applies the ``[character_name]`` value as the main Agent's character name.
- If the file or the key is absent, or the file is malformed, the name falls back to the default ``main-agent``.
- The refreshed name is process-wide: it governs how the main Agent is addressed in History, the frontend, and multi-Agent routing.

## When to Use
- After you have edited ``[character_name]`` in ``ws:SOUL.md.meta`` and want the new name to take effect immediately.
- Changes apply only after this tool runs; editing the file alone does not reload the name.

## Returns
```json
{ "success": true, "main_agent_character_name": "<name>", "soul_meta_file": "ws:SOUL.md.meta", "meta_key": "character_name" }
```""",
    "parameters": {
        "type": "object",
        "properties": {},
    },
}


class RefreshIdentityTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            name="RefreshIdentity",
            toolset="core",
            schema=_REFRESH_IDENTITY_SCHEMA,
            danger_level=ToolDangerLevel.safe,
            availability=ToolAvailability.MAIN,
        )

    def handle(self, execution: ToolExecution) -> ToolHandlerResult:
        del execution
        runtime = Application.current().get_system(RuntimeSystem)
        new_name = runtime.refresh_main_agent_character_name(_DEFAULT_SOUL_FILE)
        return ToolHandlerResult(
            result=tool_result(
                success=True,
                main_agent_character_name=new_name,
                soul_meta_file=f"ws:{_DEFAULT_SOUL_FILE}.meta",
                meta_key=SOUL_META_CHARACTER_NAME_KEY,
            )
        )


TOOLSET = BaseToolSet(
    name="core",
    tools=(RefreshIdentityTool(),),
)
