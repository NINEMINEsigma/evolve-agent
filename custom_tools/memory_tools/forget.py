from __future__ import annotations

from easysave import save, load
import logging
from typing import * # type: ignore

from abstract.tools.registry import registry, tool_result

if TYPE_CHECKING:
    from entry.base_agent_loop import ToolContext

logger = logging.getLogger(__name__)

__VERSION__ = "v0"


def _handle_forget(args: dict[str, Any], context: ToolContext | None = None) -> dict:
    """忘记一条信息。"""
    id = args["id"]
    if context:
        memory_data_file = (context.runtime_context.agentspace/"memory_data.json").absolute()
        memory_data: dict[str, str]
        if memory_data_file.exists():
            memory_data = load(__VERSION__, str(memory_data_file), dict[str, str])
        else:
            memory_data = {}
        if id not in memory_data:
            return tool_result(success=False, message=f"id {id} is not found.")
        del memory_data[id]
        save(__VERSION__, str(memory_data_file), memory_data)
    return tool_result(success=True, message=f"id {id} has been forgotten.")


# ── 注册 ─────────────────────────────────────────────────────

registry.register(
    name="forget",
    toolset="memory_tools",
    schema={
        # 从记忆存储中删除指定 id 的记忆项。
        # 前置条件：无。
        # 调用效果：如果 id 存在则删除；否则返回错误。
        # 返回值：{ success: bool, message: string }
        # 何时使用：需要移除过期、错误或不再需要的记忆时。
        # 副作用：修改磁盘上的记忆文件；删除后的条目不再被 remember_memory hook 召回。
        "description": """Remove a memory entry from long-term memory by id.

## Prerequisites
None.

## Effect
Deletes the entry with the given id from the agent's memory file. If the id does not exist, returns an error.

## Returns
```json
{ "success": true, "message": "id <id> has been forgotten." }
```
When the id is not found:
```json
{ "success": false, "message": "id <id> is not found." }
```

## When to Use
- Removing outdated or incorrect memories.
- Cleaning up temporary entries that are no longer needed.

## Side Effects
Writes to the agent's memory file on disk. Deleted entries are no longer recalled by the remember_memory hook.""",
        "parameters": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    # 要删除的记忆项的唯一标识符。
                    "description": """The unique identifier of the memory entry to delete.""",
                },
            },
            "required": ["id"],
        },
    },
    handler=_handle_forget,
    is_async=False,
)